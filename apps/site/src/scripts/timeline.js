// scripts/timeline.js
document.addEventListener('DOMContentLoaded', () => {
    // Find all timeline elements and initialize them
    document.querySelectorAll('.timeline').forEach(timeline => {
      const id = timeline.id;
      if (id) initTimelineInteractions(id);
    });
  });
  
  document.addEventListener('astro:page-load', () => {
    // Re-initialize after page transitions
    document.querySelectorAll('.timeline').forEach(timeline => {
      const id = timeline.id;
      if (id) initTimelineInteractions(id);
    });
  });
  
  function initTimelineInteractions(id) {
    const timelineEl = document.getElementById(id);
    if (!timelineEl) return;
    
    // Handle interaction with timeline events (for mobile/touch)
    timelineEl.querySelectorAll('.timeline-event').forEach(event => {
      event.addEventListener('click', (e) => {
        // Only prevent default if clicking the node or connector
        const target = e.target;
        if (target.classList.contains('timeline-node') || 
            target.classList.contains('timeline-connector')) {
          e.preventDefault();
          
          // Toggle active state
          const eventEl = event;
          const isActive = eventEl.classList.contains('active');
          
          // Remove active class from all events
          timelineEl.querySelectorAll('.timeline-event').forEach(el => 
            el.classList.remove('active')
          );
          
          // Add active class to this event unless it was already active
          if (!isActive) {
            eventEl.classList.add('active');
          }
        }
      });
    });
    
    // Add hover effects for connected events
    timelineEl.querySelectorAll('.timeline-event').forEach(event => {
      const era = event.getAttribute('data-era');
      if (!era) return;
      
      event.addEventListener('mouseenter', () => {
        // Highlight all events from the same era
        timelineEl.querySelectorAll(`.timeline-event[data-era="${era}"]`).forEach(relatedEvent => {
          if (relatedEvent !== event) {
            relatedEvent.classList.add('related-active');
          }
        });
      });
      
      event.addEventListener('mouseleave', () => {
        // Remove highlight from all events
        timelineEl.querySelectorAll('.related-active').forEach(el => {
          el.classList.remove('related-active');
        });
      });
    });
  }
  
  // Additional functionality for TimelineController if used
  document.addEventListener('DOMContentLoaded', initAllTimelineControllers);
  document.addEventListener('astro:page-load', initAllTimelineControllers);
  
  // Add Swup hooks if available
  if (window.swup?.hooks) {
    window.swup.hooks.on('content:replace', initAllTimelineControllers);
  }
  document.addEventListener('swup:enable', () => {
    if (window.swup?.hooks) {
      window.swup.hooks.on('content:replace', initAllTimelineControllers);
    }
  });
  
  // Initialize all timeline controllers
  function initAllTimelineControllers() {
    document.querySelectorAll('[data-controller-id]').forEach(controllerEl => {
      const controllerId = controllerEl.getAttribute('data-controller-id');
      if (!controllerId) return;
      
      setTimeout(() => {
        initTimelineController(controllerId);
      }, 100);
    });
  }
  
  // Timeline controller initialization
  function initTimelineController(controllerId) {
    // Check if controller already initialized
    if (window.timelineControllers && window.timelineControllers[controllerId]) {
      return;
    }
    
    // Define global object for controllers if not exists
    window.timelineControllers = window.timelineControllers || {};
    
    // Create controller object
    const controller = {};
    
    // Store controller
    window.timelineControllers[controllerId] = controller;
    
    // Get DOM elements
    const controllerEl = document.querySelector(`[data-controller-id="${controllerId}"]`);
    const viewport = document.getElementById(`timeline-viewport-${controllerId}`);
    const wrapper = document.getElementById(`timeline-wrapper-${controllerId}`);
    const timelineContainer = wrapper?.querySelector('.timeline-container');
    
    if (!controllerEl || !viewport || !wrapper || !timelineContainer) {
      console.warn(`Missing elements for controller ${controllerId}`);
      return;
    }
    
    // Initialize state
    let scale = 100;
    let offsetX = 0;
    let offsetY = 0;
    let isDragging = false;
    let startDragX = 0;
    let startDragY = 0;
    let startOffsetX = 0;
    let startOffsetY = 0;
    
    // Zoom and pan functions
    function zoomIn() {
      scale = Math.min(500, scale + 20);
      updateTransform();
    }
    
    function zoomOut() {
      const minScale = calculateMinScale();
      scale = Math.max(minScale, scale - 20);
      updateTransform();
    }
    
    function panLeft() {
      offsetX += 50;
      updateTransform();
    }
    
    function panRight() {
      offsetX -= 50;
      updateTransform();
    }
    
    function panUp() {
      offsetY += 30;
      updateTransform();
    }
    
    function panDown() {
      offsetY -= 30;
      updateTransform();
    }
    
    // Calculate minimum scale that fits viewport
    function calculateMinScale() {
      return 50;
    }
    
    // Update visible year range display
    function updateVisibleYearRange() {
      const timeline = document.querySelector(`#timeline-wrapper-${controllerId} .timeline`);
      if (!timeline) return;
      
      const baseStartYear = parseInt(timeline.getAttribute('data-start-year') || '0');
      const baseEndYear = parseInt(timeline.getAttribute('data-end-year') || '0');
      if (!baseStartYear || !baseEndYear) return;
      
      const yearSpan = baseEndYear - baseStartYear;
      const viewportWidth = viewport.offsetWidth;
      const containerWidth = timelineContainer.scrollWidth;
      const scaleFactor = scale / 100;
      
      const visiblePortion = (viewportWidth / (containerWidth * scaleFactor));
      const visibleYearSpan = yearSpan * visiblePortion;
      const centerOffset = offsetX / (containerWidth * scaleFactor / 2);
      const middleYear = baseStartYear + yearSpan / 2 - (yearSpan * centerOffset / 2);
      
      const visibleStartYear = Math.round(middleYear - visibleYearSpan / 2);
      const visibleEndYear = Math.round(middleYear + visibleYearSpan / 2);
      
      const yearDisplay = document.getElementById(`timeline-year-display-${controllerId}`);
      if (yearDisplay) {
        yearDisplay.textContent = `Visible: ${visibleStartYear} to ${visibleEndYear} (full range: ${baseStartYear} to ${baseEndYear})`;
      }
    }
    
    // Update transform with boundaries
    function updateTransform() {
      // Scale must never be smaller than minimum scale
      const minScale = Math.max(50, calculateMinScale());
      scale = Math.max(minScale, scale);
      
      // Calculate scale factor (1.0 = 100%)
      const scaleFactor = scale / 100;
      
      // Calculate container dimensions
      const containerWidth = timelineContainer.scrollWidth || 1000;
      const containerHeight = timelineContainer.scrollHeight || 500;
      const viewportWidth = viewport.offsetWidth || 800;
      const viewportHeight = viewport.offsetHeight || 400;
      
      // Calculate maximum offset with increased limits
      const maxOffsetX = Math.max(0, (containerWidth * scaleFactor * 3 - viewportWidth) / 2);
      const maxOffsetY = Math.max(0, (containerHeight * scaleFactor * 2 - viewportHeight) / 2);
      
      // Apply gentle resistance when moving far from center
      if (Math.abs(offsetX) > maxOffsetX) {
        offsetX = offsetX > 0
          ? maxOffsetX + (offsetX - maxOffsetX) * 0.5
          : -maxOffsetX + (offsetX + maxOffsetX) * 0.5;
      }
      
      if (Math.abs(offsetY) > maxOffsetY) {
        offsetY = offsetY > 0
          ? maxOffsetY + (offsetY - maxOffsetY) * 0.5
          : -maxOffsetY + (offsetY + maxOffsetY) * 0.5;
      }
      
      // Apply transform
      timelineContainer.style.setProperty('transform-origin', 'center', 'important');
      timelineContainer.style.setProperty('width', '100%', 'important');
      timelineContainer.style.setProperty('height', '100%', 'important');
      
      let transform = `scale(${scaleFactor})`;
      
      if (scale > 0) {
        transform += ` translateX(${offsetX / scaleFactor}px)`;
        transform += ` translateY(${offsetY / scaleFactor}px)`;
      }
      
      timelineContainer.style.setProperty('transform', transform, 'important');
      timelineContainer.style.setProperty('will-change', 'transform', 'important');
      timelineContainer.style.setProperty('min-width', 'auto', 'important');
      timelineContainer.style.setProperty('max-width', 'none', 'important');
      
      // Update background
      updateBackgroundTransform(scaleFactor, offsetX, offsetY, maxOffsetX, maxOffsetY);
      
      // Update year range display
      updateVisibleYearRange();
    }
    
    // Update background transform
    function updateBackgroundTransform(scaleFactor, offsetX, offsetY, maxOffsetX, maxOffsetY) {
      // Find active view
      const activeView = document.querySelector(`#timeline-wrapper-${controllerId}:not(.hidden)`) 
                        ? 'timeline' 
                        : document.querySelector(`#list-view-${controllerId}:not(.hidden)`)
                          ? 'list'
                          : document.querySelector(`#tree-view-${controllerId}:not(.hidden)`)
                            ? 'tree'
                            : document.querySelector(`#map-view-${controllerId}:not(.hidden)`)
                              ? 'map'
                              : 'timeline';
      
      // Get the container for the active view
      let bgContainer;
      
      if (activeView === 'timeline') {
        bgContainer = wrapper.querySelector('.timeline .absolute.inset-0');
      } else {
        bgContainer = document.getElementById(`${activeView}-view-${controllerId}`)?.querySelector('.absolute.inset-0');
      }
      
      if (!bgContainer) return;
      
      const imgElement = bgContainer.querySelector('img');
      if (!imgElement) return;
      
      // Calculate background transform
      const bgScaleFactor = Math.max(1.05, scaleFactor * 1.05);
      let bgTransform = `scale(${bgScaleFactor})`;
      
      const followFactor = 1.5;
      
      if (maxOffsetX > 0) {
        const bgOffsetX = offsetX / (scaleFactor * followFactor);
        bgTransform += ` translateX(${bgOffsetX}px)`;
      }
      
      if (maxOffsetY > 0) {
        const bgOffsetY = offsetY / (scaleFactor * followFactor);
        bgTransform += ` translateY(${bgOffsetY}px)`;
      }
      
    imgElement.style.transform = bgTransform;
    imgElement.style.willChange = 'transform';
    imgElement.style.transition = 'none'; // Remove transition for immediate updates
  }
  
  // Direct transform for dragging
  function updateTransformDirect() {
    // Scale must never be smaller than minimum scale
    const minScale = Math.max(50, calculateMinScale());
    scale = Math.max(minScale, scale);
    
    // Calculate scale factor (1.0 = 100%)
    const scaleFactor = scale / 100;
    
    // Calculate dimensions
    const containerWidth = timelineContainer.scrollWidth || 1000;
    const containerHeight = timelineContainer.scrollHeight || 500;
    const viewportWidth = viewport.offsetWidth || 800;
    const viewportHeight = viewport.offsetHeight || 400;
    
    // Calculate maximum offset with increased limits
    const maxOffsetX = Math.max(0, (containerWidth * scaleFactor * 3 - viewportWidth) / 2);
    const maxOffsetY = Math.max(0, (containerHeight * scaleFactor * 2 - viewportHeight) / 2);
    
    // Apply resistance when moving far from center
    if (Math.abs(offsetX) > maxOffsetX) {
      offsetX = offsetX > 0
        ? maxOffsetX + (offsetX - maxOffsetX) * 0.5
        : -maxOffsetX + (offsetX + maxOffsetX) * 0.5;
    }
    
    if (Math.abs(offsetY) > maxOffsetY) {
      offsetY = offsetY > 0
        ? maxOffsetY + (offsetY - maxOffsetY) * 0.5
        : -maxOffsetY + (offsetY + maxOffsetY) * 0.5;
    }
    
    // Apply transform
    timelineContainer.style.transformOrigin = 'center';
    timelineContainer.style.width = '100%';
    timelineContainer.style.height = '100%';
    
    let transform = `scale(${scaleFactor})`;
    transform += ` translateX(${offsetX / scaleFactor}px)`;
    transform += ` translateY(${offsetY / scaleFactor}px)`;
    
    timelineContainer.style.transform = transform;
    timelineContainer.style.willChange = 'transform';
    timelineContainer.style.minWidth = 'auto';
    timelineContainer.style.maxWidth = 'none';
    
    // Update background
    updateBackgroundDirect(scaleFactor, offsetX, offsetY, maxOffsetX, maxOffsetY);
  }
  
  // Direct background update for dragging
  function updateBackgroundDirect(scaleFactor, offsetX, offsetY, maxOffsetX, maxOffsetY) {
    const bgContainer = wrapper.querySelector('.timeline .absolute.inset-0');
    const imgElement = bgContainer?.querySelector('img');
    
    if (!imgElement) return;
    
    // Calculate background transform
    const bgScaleFactor = Math.max(1.05, scaleFactor * 1.05);
    let bgTransform = `scale(${bgScaleFactor})`;
    
    const followFactor = 1.25;
    
    if (maxOffsetX > 0) {
      const bgOffsetX = offsetX / (scaleFactor * followFactor);
      bgTransform += ` translateX(${bgOffsetX}px)`;
    }
    
    if (maxOffsetY > 0) {
      const bgOffsetY = offsetY / (scaleFactor * followFactor);
      bgTransform += ` translateY(${bgOffsetY}px)`;
    }
    
    imgElement.style.transform = bgTransform;
    imgElement.style.willChange = 'transform';
  }
  
  // Set up event handlers
  function bindEvents() {
    // Button handlers
    const zoomInBtn = document.getElementById(`zoom-in-btn-${controllerId}`);
    const zoomOutBtn = document.getElementById(`zoom-out-btn-${controllerId}`);
    const panLeftBtn = document.getElementById(`pan-left-btn-${controllerId}`);
    const panRightBtn = document.getElementById(`pan-right-btn-${controllerId}`);
    const panUpBtn = document.getElementById(`pan-up-btn-${controllerId}`);
    const panDownBtn = document.getElementById(`pan-down-btn-${controllerId}`);
    const resetViewBtn = document.getElementById(`reset-view-btn-${controllerId}`);
    const focusEventsBtn = document.getElementById(`focus-events-btn-${controllerId}`);
    
    if (zoomInBtn) zoomInBtn.addEventListener('click', (e) => {
      e.preventDefault();
      zoomIn();
    });
    
    if (zoomOutBtn) zoomOutBtn.addEventListener('click', (e) => {
      e.preventDefault();
      zoomOut();
    });
    
    if (panLeftBtn) panLeftBtn.addEventListener('click', (e) => {
      e.preventDefault();
      panLeft();
    });
    
    if (panRightBtn) panRightBtn.addEventListener('click', (e) => {
      e.preventDefault();
      panRight();
    });
    
    if (panUpBtn) panUpBtn.addEventListener('click', (e) => {
      e.preventDefault();
      panUp();
    });
    
    if (panDownBtn) panDownBtn.addEventListener('click', (e) => {
      e.preventDefault();
      panDown();
    });
    
    if (resetViewBtn) resetViewBtn.addEventListener('click', (e) => {
      e.preventDefault();
      scale = 100;
      offsetX = 0;
      offsetY = 0;
      updateTransform();
      
      // Also reset the era filter
      const eraSelect = document.getElementById(`era-select-${controllerId}`);
      if (eraSelect) {
        eraSelect.value = 'all';
        filterByEra('all');
      }
    });
    
    if (focusEventsBtn) focusEventsBtn.addEventListener('click', (e) => {
      e.preventDefault();
      
      // Reset to initial position focusing on the events
      scale = 100;
      offsetX = 0;
      offsetY = 0;
      updateTransform();
    });
    
    // Dragging handlers
    viewport.addEventListener('mousedown', startDrag);
    window.addEventListener('mousemove', dragTimeline);
    window.addEventListener('mouseup', endDrag);
    
    // View mode handlers
    const compactBtn = document.getElementById(`compact-view-btn-${controllerId}`);
    const expandedBtn = document.getElementById(`expanded-view-btn-${controllerId}`);
    
    if (compactBtn) compactBtn.addEventListener('click', (e) => {
      e.preventDefault();
      wrapper.classList.add('compact-mode');
      wrapper.classList.remove('expanded-mode');
      compactBtn.classList.add('text-[var(--primary)]');
      if (expandedBtn) expandedBtn.classList.remove('text-[var(--primary)]');
      
      setTimeout(updateTransform, 100);
    });
    
    if (expandedBtn) expandedBtn.addEventListener('click', (e) => {
      e.preventDefault();
      wrapper.classList.remove('compact-mode');
      wrapper.classList.add('expanded-mode');
      expandedBtn.classList.add('text-[var(--primary)]');
      if (compactBtn) compactBtn.classList.remove('text-[var(--primary)]');
      
      setTimeout(updateTransform, 100);
    });
    
    // Era filter
    const eraSelect = document.getElementById(`era-select-${controllerId}`);
    if (eraSelect) {
      eraSelect.addEventListener('change', (e) => {
        filterByEra(e.target.value);
      });
    }
    
    // View switcher
    initViewSwitcher();
    
    // Add scroll handlers
    initScrollHandlers();
    
    // Resize handler
    window.addEventListener('resize', updateTransform);
  }
  
  // Filter events by era
  function filterByEra(era) {
    // Timeline events
    const timelineEvents = wrapper.querySelectorAll('.timeline-event');
    
    // Get all the elements that can be filtered
    const listView = document.getElementById(`list-view-${controllerId}`);
    const treeView = document.getElementById(`tree-view-${controllerId}`);
    const mapView = document.getElementById(`map-view-${controllerId}`);
    
    const listEvents = listView ? listView.querySelectorAll('.timeline-event-card') : [];
    const treeEvents = treeView ? treeView.querySelectorAll('.timeline-tree-node') : [];
    const mapEvents = mapView ? mapView.querySelectorAll('.location-card') : [];
    const mapPins = mapView ? mapView.querySelectorAll('.map-pin') : [];
    
    // Reset all events if "all" is selected
    if (era === 'all') {
      [timelineEvents, listEvents, treeEvents, mapEvents, mapPins].forEach(elements => {
        elements.forEach(element => {
          element.style.opacity = '1';
          element.style.display = '';
          element.classList.remove('filtered-out');
        });
      });
      return;
    }
    
    // Apply filtering to each view
    applyFilter(timelineEvents, 'data-era', era);
    applyFilter(listEvents, 'data-era', era);
    applyFilter(treeEvents, 'data-era', era);
    applyFilter(mapEvents, 'data-era', era);
    applyFilter(mapPins, 'data-era', era);
  }
  
  // Helper function to apply filtering consistently
  function applyFilter(elements, attributeName, targetValue) {
    elements.forEach(element => {
      const elementValue = element.getAttribute(attributeName);
      
      if (elementValue === targetValue) {
        // Element matches filter - show it prominently
        element.style.opacity = '1';
        element.style.display = '';
        element.classList.remove('filtered-out');
      } else {
        // Element doesn't match filter - grey it out
        element.style.opacity = '0.25';
        element.classList.add('filtered-out');
      }
    });
  }
  
  // Function to handle scrollable content
  function initScrollHandlers() {
    // Find all scrollable containers
    const scrollContainers = document.querySelectorAll('.scrollbar-timeline');
    
    scrollContainers.forEach(container => {
      // Add scroll event listener to each container
      container.addEventListener('scroll', function() {
        // Check if we're near the bottom
        const isAtBottom = this.scrollHeight - this.scrollTop - this.clientHeight < 30;
        
        // Add/remove class based on scroll position
        if (isAtBottom) {
          this.classList.add('at-bottom');
        } else {
          this.classList.remove('at-bottom');
        }
      });
    });
  }
  
  // Initialize view switcher
  function initViewSwitcher() {
    const viewButtons = document.querySelectorAll(`#view-switcher-${controllerId} .timeline-view-btn`);
    const timelineView = document.getElementById(`timeline-wrapper-${controllerId}`);
    const listView = document.getElementById(`list-view-${controllerId}`);
    const treeView = document.getElementById(`tree-view-${controllerId}`);
    const mapView = document.getElementById(`map-view-${controllerId}`);
    
    if (!viewButtons.length || !timelineView || !listView || !treeView || !mapView) {
      console.warn("Missing view elements");
      return;
    }
    
    viewButtons.forEach(button => {
      button.addEventListener('click', () => {
        // Get view type from data attribute
        const viewType = button.getAttribute('data-view') || "timeline";
        
        // Update button styles
        viewButtons.forEach(btn => {
          if (btn.getAttribute('data-view') === viewType) {
            btn.classList.add('bg-[var(--primary)]', 'text-white');
            btn.classList.remove('bg-[var(--btn-regular-bg)]', 'text-[var(--btn-content)]');
          } else {
            btn.classList.remove('bg-[var(--primary)]', 'text-white');
            btn.classList.add('bg-[var(--btn-regular-bg)]', 'text-[var(--btn-content)]');
          }
        });
        
        // Show/hide appropriate view
        timelineView.classList.toggle('hidden', viewType !== 'timeline');
        listView.classList.toggle('hidden', viewType !== 'list');
        treeView.classList.toggle('hidden', viewType !== 'tree');
        mapView.classList.toggle('hidden', viewType !== 'map');
        
        // Wait for the view to become visible
        setTimeout(initScrollHandlers, 200);
        
        // Save preference
        localStorage.setItem(`timeline-view-${controllerId}`, viewType);
      });
    });
    
    // Load saved preference
    const savedView = localStorage.getItem(`timeline-view-${controllerId}`);
    if (savedView) {
      const targetButton = document.querySelector(`#view-switcher-${controllerId} .timeline-view-btn[data-view="${savedView}"]`);
      if (targetButton) {
        targetButton.click();
      }
    }
  }
  
  // Dragging functions
  function startDrag(e) {
    isDragging = true;
    startDragX = e.clientX;
    startDragY = e.clientY;
    startOffsetX = offsetX;
    startOffsetY = offsetY;
    
    // Add dragging class to disable all transitions
    document.body.style.cursor = 'grabbing';
    viewport.classList.add('dragging');
    wrapper.querySelector('.timeline')?.classList.add('dragging');
    
    // Apply transform changes immediately
    updateTransformDirect();
    
    e.preventDefault();
  }
  
  function dragTimeline(e) {
    if (!isDragging) return;
    
    // Calculate new offsets
    const deltaX = e.clientX - startDragX;
    const deltaY = e.clientY - startDragY;
    
    offsetX = startOffsetX + deltaX;
    offsetY = startOffsetY + deltaY;
    
    // Apply transform directly
    updateTransformDirect();
  }
  
  function endDrag() {
    if (!isDragging) return;
    
    isDragging = false;
    document.body.style.cursor = '';
    viewport.classList.remove('dragging');
    wrapper.querySelector('.timeline')?.classList.remove('dragging');
  }
  
  // Initialize controller
  bindEvents();
  
  // Initial transform application after DOM rendering
  setTimeout(() => {
    updateTransform();
    setTimeout(updateTransform, 200);
  }, 100);
}