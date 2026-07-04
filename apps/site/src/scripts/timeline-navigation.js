/**
 * Timeline Navigation Component
 * Handles the interactive timeline navigation with list, tree, and map views
 */

class TimelineNavigation extends HTMLElement {
    constructor() {
      super();
      
      // Initialize after the DOM is fully loaded
      if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => {
          this.init();
        });
      } else {
        this.init();
      }
    }
    
    init() {
      // Only initialize once
      if (this.hasAttribute('data-initialized')) return;
      this.setAttribute('data-initialized', 'true');
      
      this.initViewSwitcher();
      this.initMapInteractions();
      this.initTreeNodes();
    }
    
    initViewSwitcher() {
      const viewButtons = this.querySelectorAll('.timeline-view-btn');
      const views = this.querySelectorAll('.timeline-view');
      const navigationId = this.id;
      
      viewButtons.forEach(button => {
        button.addEventListener('click', () => {
          // Get view type from data attribute
          const viewType = button.getAttribute('data-view') || "list";
          
          // Update button state
          viewButtons.forEach(btn => {
            if (btn.getAttribute('data-view') === viewType) {
              btn.classList.add('bg-[var(--primary)]', 'text-white');
              btn.classList.remove('bg-[var(--btn-regular-bg)]', 'text-[var(--btn-content)]');
            } else {
              btn.classList.remove('bg-[var(--primary)]', 'text-white');
              btn.classList.add('bg-[var(--btn-regular-bg)]', 'text-[var(--btn-content)]');
            }
          });
          
          // Show selected view, hide others
          views.forEach(view => {
            if (view.id === `${viewType}-view-${navigationId}`) {
              view.classList.remove('hidden');
            } else {
              view.classList.add('hidden');
            }
          });
          
          // Update data attribute for state tracking
          this.setAttribute('data-view', viewType);
          
          // Save preference
          localStorage.setItem('timeline-view-preference', viewType);
        });
      });
      
      // Load saved preference
      const savedView = localStorage.getItem('timeline-view-preference');
      if (savedView) {
        const targetButton = this.querySelector(`.timeline-view-btn[data-view="${savedView}"]`);
        if (targetButton) {
          targetButton.click();
        }
      }
    }
    
    initMapInteractions() {
      // Add hover effects to map pins
      const mapPins = this.querySelectorAll('.map-pin');
      const locationCards = this.querySelectorAll('.location-card');
      
      mapPins.forEach(pin => {
        const slug = pin.getAttribute('data-event-slug');
        
        // Highlight related location card when hovering over a map pin
        pin.addEventListener('mouseenter', () => {
          // Make the pin larger
          const circle = pin.querySelector('circle');
          if (circle) {
            const originalRadius = circle.getAttribute('r');
            circle.setAttribute('data-original-radius', originalRadius || '5');
            circle.setAttribute('r', parseFloat(originalRadius || '5') * 1.5 + '');
          }
          
          // Find and highlight matching location card
          locationCards.forEach(card => {
            const href = card.getAttribute('href');
            if (href && slug && href.includes(slug)) {
              card.classList.add('bg-[var(--btn-card-bg-hover)]');
            }
          });
        });
        
        pin.addEventListener('mouseleave', () => {
          // Reset pin to original size
          const circle = pin.querySelector('circle');
          if (circle) {
            const originalRadius = circle.getAttribute('data-original-radius');
            if (originalRadius) {
              circle.setAttribute('r', originalRadius);
            }
          }
          
          // Remove highlighting from location cards
          locationCards.forEach(card => {
            card.classList.remove('bg-[var(--btn-card-bg-hover)]');
          });
        });
        
        // Make the pins clickable
        pin.addEventListener('click', () => {
          const slug = pin.getAttribute('data-event-slug');
          if (slug) {
            window.location.href = `/posts/${slug}/`;
          }
        });
      });
    }
    
    initTreeNodes() {
      // Add animation effects for tree view nodes
      const treeNodes = this.querySelectorAll('.timeline-tree-node');
      
      treeNodes.forEach((node, index) => {
        // Add delayed entrance animation
        setTimeout(() => {
          node.classList.add('tree-node-visible');
        }, index * 50);
        
        // Connect related events by era
        node.addEventListener('mouseenter', () => {
          const eraElement = node.querySelector('.rounded-full');
          const era = eraElement ? eraElement.textContent?.trim() : null;
          if (!era) return;
          
          treeNodes.forEach(otherNode => {
            const otherEraElement = otherNode.querySelector('.rounded-full');
            const otherEra = otherEraElement ? otherEraElement.textContent?.trim() : null;
            if (otherNode !== node && otherEra === era) {
              otherNode.classList.add('related-node');
            }
          });
        });
        
        node.addEventListener('mouseleave', () => {
          treeNodes.forEach(otherNode => {
            otherNode.classList.remove('related-node');
          });
        });
      });
    }
  }
  
  // Register the custom element
  customElements.define('timeline-navigation', TimelineNavigation);
  
  // Initialize on Astro page transitions
  document.addEventListener('astro:page-load', () => {
    document.querySelectorAll('timeline-navigation').forEach(component => {
      if (component instanceof TimelineNavigation) {
        component.init();
      }
    });
  });