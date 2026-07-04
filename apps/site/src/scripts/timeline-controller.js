/**
 * Timeline Controller
 * Handles the interactive timeline with zoom, pan and filtering capabilities
 */

// Define a global object to store controller functions
window.timelineControllers = window.timelineControllers || {};

// Function to initialize all controllers on the page
function initAllTimelineControllers() {
  document.querySelectorAll('[data-controller-id]').forEach(controllerEl => {
    const controllerId = controllerEl.getAttribute('data-controller-id');
    if (!controllerId) return;
    
    setTimeout(() => {
      initTimelineController(controllerId);
    }, 100);
  });
}

// Initialize when DOM is ready and after page transitions
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

// Main controller initialization function
function initTimelineController(controllerId) {
  // Check if controller already initialized
  if (window.timelineControllers[controllerId]) {
    return;
  }
  
  // Create controller object
  const controller = {};
  
  // Store controller
  window.timelineControllers[controllerId] = controller;
  
  console.log(`Initializing timeline controller: ${controllerId}`);
  
  // Get DOM elements
  const controllerEl = document.querySelector(`[data-controller-id="${controllerId}"]`);
  const viewport = document.getElementById(`timeline-viewport-${controllerId}`);
  const wrapper = document.getElementById(`timeline-wrapper-${controllerId}`);
  const timelineContainer = wrapper?.querySelector('.timeline-container');
  
  if (!controllerEl || !viewport || !wrapper || !timelineContainer) {
    console.warn(`Missing elements for controller ${controllerId}`);
    return;
  }
  
  // Debug element selection
  console.log("Timeline container found:", !!timelineContainer, timelineContainer);
  if (!timelineContainer) {
    console.error("Timeline container not found in:", wrapper);
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
  let lastUpdateTime = 0;
  
  // Add reset button
  const controlsContainer = controllerEl.querySelector('.timeline-controls .flex');
  if (controlsContainer) {
    const resetButton = document.createElement('button');
    resetButton.className = 'flex items-center justify-center w-8 h-8 rounded-md mr-1 text-black/75 dark:text-white/75 hover:bg-gray-100 dark:hover:bg-gray-700 hover:text-[var(--primary)] transition-all';
    resetButton.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M4 2a1 1 0 011 1v2.101a7.002 7.002 0 0111.601 2.566 1 1 0 11-1.885.666A5.002 5.002 0 005.999 7H9a1 1 0 010 2H4a1 1 0 01-1-1V3a1 1 0 011-1zm.008 9.057a1 1 0 011.276.61A5.002 5.002 0 0014.001 13H11a1 1 0 110-2h5a1 1 0 011 1v5a1 1 0 11-2 0v-2.101a7.002 7.002 0 01-11.601-2.566 1 1 0 01.61-1.276z" clip-rule="evenodd" /></svg>';
    resetButton.setAttribute('aria-label', 'Reset View');
    
    const divider = document.createElement('div');
    divider.className = 'h-5 border-r border-black/10 dark:border-white/10 mx-2';
    
    controlsContainer.appendChild(divider);
    controlsContainer.appendChild(resetButton);
    
    resetButton.addEventListener('click', (e) => {
      e.preventDefault();
      scale = 100;
      offsetX = 0;
      offsetY = 0;
      updateTransform();
    });
  }
  
  // Zoom and pan functions
  function zoomIn() {
    console.log('Zoom in');
    scale = Math.min(300, scale + 20); // Allow more zoom
    updateTransform();
  }
  
  function zoomOut() {
    console.log('Zoom out');
    const minScale = calculateMinScale();
    scale = Math.max(minScale, scale - 20); // Stop at minimum scale
    if (scale <= minScale) {
      offsetX = 0; // Reset position when zoomed to minimum
    }
    updateTransform();
  }
  
  function panLeft() {
    if (scale <= 100) return;
    offsetX += 50;
    updateTransform();
  }
  
  function panRight() {
    if (scale <= 100) return;
    offsetX -= 50;
    updateTransform();
  }
  
  function panUp() {
    if (scale <= 100) return;
    offsetY += 30;
    updateTransform();
  }
  
  function panDown() {
    if (scale <= 100) return;
    offsetY -= 30;
    updateTransform();
  }
  
  // Calculate minimum scale that fits viewport
  function calculateMinScale() {
    return 100; // Default to 100%
  }
  
  // Apply transforms with boundaries
  function updateTransform() {
    // Throttle updates to prevent too many calls
    const now = Date.now();
    if (now - lastUpdateTime < 16) {
      return;
    }
    lastUpdateTime = now;
    
    // Scale must never be smaller than 100%
    const minScale = Math.max(100, calculateMinScale());
    scale = Math.max(minScale, scale);
    
    // Calculate scale factor (1.0 = 100%)
    const scaleFactor = scale / 100;
    
    // Calculate maximum offset based on scale
    const containerWidth = timelineContainer.scrollWidth || 1000;
    const containerHeight = timelineContainer.scrollHeight || 500;
    const viewportWidth = viewport.offsetWidth || 800;
    const viewportHeight = viewport.offsetHeight || 400;
    
    // Maximum offset depends on how much bigger the scaled timeline is than the viewport
    const maxOffsetX = Math.max(0, (containerWidth * scaleFactor - viewportWidth) / 2);
    const maxOffsetY = Math.max(0, (containerHeight * scaleFactor - viewportHeight) / 2);
    
    // Limit offsets to valid ranges
    offsetX = Math.max(-maxOffsetX, Math.min(maxOffsetX, offsetX));
    offsetY = Math.max(-maxOffsetY, Math.min(maxOffsetY, offsetY));
    
    // Set the transform-origin to center for proper zooming
    timelineContainer.style.setProperty('transform-origin', 'center', 'important');
    timelineContainer.style.setProperty('width', '100%', 'important');
    timelineContainer.style.setProperty('height', '100%', 'important');
    
    // Apply transforms with scale AND translate for center-based zooming
    let transform = `scale(${scaleFactor})`;
    
    if (scale > 100) {
      // Add translations after scaling (if needed)
      if (maxOffsetX > 0) {
        transform += ` translateX(${offsetX / scaleFactor}px)`;
      }
      
      if (maxOffsetY > 0) {
        transform += ` translateY(${offsetY / scaleFactor}px)`;
      }
    }
    
    // Apply the combined transform
    timelineContainer.style.setProperty('transform', transform, 'important');

    // Ensure overflow is visible
    timelineContainer.style.setProperty('min-width', 'auto', 'important');
    timelineContainer.style.setProperty('max-width', 'none', 'important');
    
    console.log(`Transform updated: scale=${scale}%, transform=${transform}, maxOffsetX=${maxOffsetX}, maxOffsetY=${maxOffsetY}`);
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
      
      // Update after mode change
      setTimeout(updateTransform, 100);
    });
    
    if (expandedBtn) expandedBtn.addEventListener('click', (e) => {
      e.preventDefault();
      wrapper.classList.remove('compact-mode');
      wrapper.classList.add('expanded-mode');
      expandedBtn.classList.add('text-[var(--primary)]');
      if (compactBtn) compactBtn.classList.remove('text-[var(--primary)]');
      
      // Update after mode change
      setTimeout(updateTransform, 100);
    });
    
    // Era filter
    const eraSelect = document.getElementById(`era-select-${controllerId}`);
    if (eraSelect) {
      eraSelect.addEventListener('change', (e) => {
        filterByEra(e.target.value);
      });
    }
    
    // Resize handler
    window.addEventListener('resize', updateTransform);
  }
  
  // Filter events by era
  function filterByEra(era) {
    const allEvents = wrapper.querySelectorAll('.timeline-event');
    
    if (era === 'all') {
      allEvents.forEach(event => {
        event.style.opacity = '1';
      });
      return;
    }
    
    allEvents.forEach(event => {
      const eventEra = event.getAttribute('data-era') || 'unknown';
      
      if (eventEra === era) {
        event.style.opacity = '1';
        
        // Highlight matching events
        event.classList.add('era-highlight');
        setTimeout(() => {
          event.classList.remove('era-highlight');
        }, 1000);
      } else {
        event.style.opacity = '0.3';
      }
    });
  }
  
  // Dragging functions
  function startDrag(e) {
    if (scale <= 100) return;
    
    isDragging = true;
    startDragX = e.clientX;
    startDragY = e.clientY;
    startOffsetX = offsetX;
    startOffsetY = offsetY;
    viewport.style.cursor = 'grabbing';
    e.preventDefault();
  }
  
  function dragTimeline(e) {
    if (!isDragging) return;
    
    const deltaX = e.clientX - startDragX;
    const deltaY = e.clientY - startDragY;
    
    offsetX = startOffsetX + deltaX;
    offsetY = startOffsetY + deltaY;
    
    updateTransform();
  }
  
  function endDrag() {
    isDragging = false;
    viewport.style.cursor = 'grab';
  }
  
  // Initialize the controller
  bindEvents();
  
  // Allow for complete DOM rendering before first transform
  setTimeout(() => {
    console.log("Initial transform application");
    updateTransform();
    
    // Apply a second update after a short delay to ensure it takes effect
    setTimeout(updateTransform, 200);
  }, 100);
}