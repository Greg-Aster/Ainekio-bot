<script lang="ts">
  import { onMount, onDestroy, createEventDispatcher } from 'svelte';
  import { tweened } from 'svelte/motion';
  import { cubicOut, linear } from 'svelte/easing';
  import StarNode from './StarNode.svelte';
  import TimelineCard from './TimelineCard.svelte';
  import type { TimelineEvent } from '../../services/TimelineService.client';
  import { 
    defaultTimelineViewConfig, 
    extractEraConfig,
    getEraConfigForYear,
    type EraConfigMap 
  } from '../../config/timelineconfig';

  // Props
  export let events: TimelineEvent[] = [];
  export let startYear: number | undefined = undefined;
  export let endYear: number | undefined = undefined;
  export let background: string = '/assets/banner/0001.png';
  export let compact: boolean = false;
  export let asBanner: boolean = false;
  export let useEraColors: boolean = false;
    
  // Internal state
  let timelineContainer: HTMLElement;
  let selectedEvent: TimelineEvent | null = null;
  let hoveredEvent: TimelineEvent | null = null;
  let containerWidth: number = 0;
  let containerHeight: number = 0;
  let padding = defaultTimelineViewConfig.padding; // Get padding from config
  let isMobile = false; // Track if we're in mobile view
  let isNavigating = false; // Track if we're navigating to a new page
  let fadeOverlayVisible = true; // Start with fade overlay visible
  let isTouchActive = false;
  let hoverTimeoutId: ReturnType<typeof setTimeout> | null = null;
  const hoverOutDelay = 300; // Delay in ms before hiding the card
  
  // Tweened stores with configurable durations
  const normalDuration = 300;
  const touchDuration = 0;  // No animation during touch
  
  const scale = tweened(defaultTimelineViewConfig.defaultZoom, {
    duration: normalDuration, 
    easing: cubicOut
  });
  
  const offsetX = tweened(0, {
    duration: normalDuration,
    easing: cubicOut
  });
  
  const offsetY = tweened(0, {
    duration: normalDuration,
    easing: cubicOut
  });
  
  const dispatch = createEventDispatcher();
  
  // Calculate actual time range from events
  $: {
    if (!startYear || !endYear) {
      if (events.length > 0) {
        const years = events.map(event => event.year);
        const minYear = Math.min(...years);
        const maxYear = Math.max(...years);
        
        // Add padding
        const yearPadding = Math.max(5, Math.ceil((maxYear - minYear) * 0.1));
        
        if (!startYear) startYear = minYear - yearPadding;
        if (!endYear) endYear = maxYear + yearPadding;
      } else {
        startYear = startYear || 2000;
        endYear = endYear || 2100;
      }
    }
  }
  
  // Calculate timespan - ensure it has a non-zero value
  $: timespan = Math.max(1, (endYear || 2100) - (startYear || 2000));
  
  // Calculate horizontal/vertical position for each event
  function getPositionPercentage(year: number, customPadding?: number): number {
    if (timespan === 0) return 50;
    
    // Use custom padding if provided, otherwise use default
    const paddingToUse = customPadding !== undefined ? customPadding : padding;
    
    // Clamp year to our display range
    const clampedYear = Math.max(startYear || 0, Math.min(endYear || 3000, year));
    
    // Calculate base percentage
    const basePercentage = ((clampedYear - (startYear || 0)) / timespan) * 100;
    
    // Apply padding to spread events away from edges
    return paddingToUse + (basePercentage * (100 - (2 * paddingToUse)) / 100);
  }
  
  // Generate positions for events on the timeline
  $: eventPositions = events.map((event, index) => {
    // Get era configuration to check for custom padding
    const eraConfigs = extractEraConfig(events);
    const eraConfig = event.era && eraConfigs[event.era] ? eraConfigs[event.era] : null;
    const customPadding = eraConfig?.customPadding;
    
    // For timeline position (horizontal in desktop, vertical in mobile)
    const posPercentage = getPositionPercentage(event.year, customPadding);
    
    // Create seed for deterministic randomization
    const seed = (event.slug.charCodeAt(0) + index) * 11 + event.year % 100;
    
    // Always use random position - no yIndex check
    const randomFactor = ((seed * 9301 + 49297) % 233280) / 233280;
    
    // Calculate random offset (works for both mobile and desktop)
    const offsetPosition = (randomFactor * 2 - 1) * 100;
    
    // Ensure values stay within reasonable bounds
    const clampedOffset = Math.max(-100, Math.min(100, offsetPosition));
    
    // Always use floating animation
    const floatClass = `floating-animation-${(seed % 5) + 1}`;
    
    return {
      event,
      timelinePosition: posPercentage, // % along the primary timeline axis
      offsetPosition: clampedOffset,   // px offset from the timeline
      floatClass,       // Animation class for floating
      shouldFloat: true  // Always float
    };
  });
  
  // Setup direct event handlers
  function setupDirectEventHandlers() {
    if (!timelineContainer) return;
    
    // Handle clicks on event elements using event delegation
    timelineContainer.addEventListener('click', (e) => {
      // Find if we clicked on an event node
      const target = e.target as HTMLElement;
      const eventNode = target.closest('.event-node');
      
      if (eventNode) {
        // Don't process click events on mobile - handled by touch
        if (isMobile) return;
        
        // Get the event slug from the data attribute
        const slug = eventNode.getAttribute('data-slug');
        if (!slug) return;
        
        // Stop event propagation
        e.stopPropagation();
        
        // Find the corresponding event
        const event = events.find(evt => evt.slug === slug);
        if (!event) return;
        
        // If already selected, navigate to post
        if (selectedEvent && selectedEvent.slug === slug) {
          navigateToPost(slug);
        } else {
          // Otherwise, select this event
          selectedEvent = event;
          dispatch('select', { event });
        }
      } else if (target === timelineContainer || target.classList.contains('timeline-container')) {
        // Click on background
        selectedEvent = null;
        hoveredEvent = null;
        dispatch('deselect');
      }
    });
    
    // Handle hover events with delay
    timelineContainer.addEventListener('mouseover', (e) => {
      const target = e.target as HTMLElement;
      const eventNode = target.closest('.event-node');
      
      if (eventNode) {
        const slug = eventNode.getAttribute('data-slug');
        if (!slug) return;
        
        const event = events.find(evt => evt.slug === slug);
        if (!event || (selectedEvent && selectedEvent.slug === slug)) return;
        
        // Cancel any pending hide timeout
        if (hoverTimeoutId) {
          clearTimeout(hoverTimeoutId);
          hoverTimeoutId = null;
        }
        
        hoveredEvent = event;
      }
    });
    
    timelineContainer.addEventListener('mouseout', (e) => {
      const target = e.target as HTMLElement;
      const eventNode = target.closest('.event-node');
      
      if (eventNode) {
        const slug = eventNode.getAttribute('data-slug');
        if (!slug) return;
        
        if (hoveredEvent && hoveredEvent.slug === slug) {
          // Set timeout to hide the card after delay
          if (hoverTimeoutId) {
            clearTimeout(hoverTimeoutId);
          }
          
          hoverTimeoutId = setTimeout(() => {
            hoveredEvent = null;
            hoverTimeoutId = null;
          }, hoverOutDelay);
        }
      }
    });
  }
  
  function navigateToPost(slug: string) {
  // Show the fade overlay
  isNavigating = true;
  fadeOverlayVisible = true;
  
  // Wait for the fade-in animation to complete before navigating
  setTimeout(() => {
    // Remove the fragment identifier to prevent automatic scrolling
    window.location.href = `/posts/${slug}/`;
  }, 300); // Match this to the CSS transition duration
}
  
  // Simple drag handling for panning
  let isDragging = false;
  let startDragX = 0;
  let startDragY = 0;
  let startOffsetX = 0;
  let startOffsetY = 0;
  
  // Touch-specific state
  let touchStartX = 0;
  let touchStartY = 0;
  let lastTouchX = 0;
  let lastTouchY = 0;
  let touchDistance = 0;
  let initialTouchDistance = 0;
  let isTouching = false;
  let isMultiTouch = false;
  let touchStartTime = 0;
  let touchMoved = false;
  let touchTarget: HTMLElement | null = null;
  let lastTapTime = 0; // Track time of last tap for double-tap detection
  
  // Helper function to update the animation duration
  function setTouchMode(enabled: boolean) {
    const duration = enabled ? touchDuration : normalDuration;
    scale.update(s => s, { duration });
    offsetX.update(x => x, { duration });
    offsetY.update(y => y, { duration });
    
    isTouchActive = enabled; // Track touch state for CSS classes
  }
  
  function startDrag(e: MouseEvent) {
    // Ignore drags that start on event elements
    if ((e.target as HTMLElement).closest('.event-node')) {
      return;
    }
    
    isDragging = true;
    startDragX = e.clientX;
    startDragY = e.clientY;
    startOffsetX = $offsetX;
    startOffsetY = $offsetY;
    document.body.style.cursor = 'grabbing';
    
    // Add class for styling
    if (timelineContainer) {
      timelineContainer.classList.add('dragging');
    }
  }
  
  function drag(e: MouseEvent) {
    if (!isDragging) return;
    
    const deltaX = e.clientX - startDragX;
    const deltaY = e.clientY - startDragY;
    
    offsetX.set(startOffsetX + deltaX);
    offsetY.set(startOffsetY + deltaY);
  }
  
  function endDrag() {
    if (!isDragging) return;
    
    isDragging = false;
    document.body.style.cursor = '';
    
    // Remove dragging class
    if (timelineContainer) {
      timelineContainer.classList.remove('dragging');
    }
  }
  
  // Handle double-click to zoom
  function handleDoubleClick(e: MouseEvent) {
    // Ignore double-clicks on event elements
    if ((e.target as HTMLElement).closest('.event-node')) {
      return;
    }
    
    // Prevent default browser behavior
    e.preventDefault();
    
    // Get the position of the double-click relative to the container
    const rect = timelineContainer.getBoundingClientRect();
    const clickX = e.clientX - rect.left;
    const clickY = e.clientY - rect.top;
    
    // Calculate the center point of the container
    const centerX = containerWidth / 2;
    const centerY = containerHeight / 2;
    
    // Calculate how far from center the click was
    const deltaX = clickX - centerX;
    const deltaY = clickY - centerY;
    
    // Zoom in, using max zoom from config
    scale.update(s => Math.min(defaultTimelineViewConfig.maxZoom, s + 0.5));
    
    // Adjust the offset to center on the click position
    // The formula is complex because we need to account for the current scale and offset
    offsetX.update(x => x - (deltaX / $scale) * 0.2);
    offsetY.update(y => y - (deltaY / $scale) * 0.2);
  }
  
  // Touch handlers for mobile navigation
  function handleTouchStart(e: TouchEvent) {
    // Store the target element
    touchTarget = e.target as HTMLElement;
    
    // Check if touch is on an event node
    const isOnEventNode = !!touchTarget.closest('.event-node');
    
    // Only prevent default if not touching on an event node
    if (!isOnEventNode) {
      e.preventDefault();
    }
    
    // Set to immediate animations during touch for smoothness
    setTouchMode(true);
    
    // Reset touch moved flag
    touchMoved = false;
    
    // Store touch start time for tap detection
    touchStartTime = Date.now();
    
    // Store the initial touch position
    if (e.touches.length === 1) {
      // Single touch - pan/drag
      isTouching = true;
      isMultiTouch = false;
      touchStartX = e.touches[0].clientX;
      touchStartY = e.touches[0].clientY;
      lastTouchX = touchStartX;
      lastTouchY = touchStartY;
      startOffsetX = $offsetX;
      startOffsetY = $offsetY;
      
      // Add dragging class only if not touching an event node
      if (timelineContainer && !isOnEventNode) {
        timelineContainer.classList.add('dragging');
      }
    } else if (e.touches.length === 2) {
      // Two touches - pinch zoom
      isTouching = true;
      isMultiTouch = true;
      
      // Calculate the initial distance between two touches
      const touch1 = e.touches[0];
      const touch2 = e.touches[1];
      initialTouchDistance = Math.hypot(
        touch2.clientX - touch1.clientX,
        touch2.clientY - touch1.clientY
      );
      touchDistance = initialTouchDistance;
      
      // Store the midpoint for panning while zooming
      touchStartX = (touch1.clientX + touch2.clientX) / 2;
      touchStartY = (touch1.clientY + touch2.clientY) / 2;
      lastTouchX = touchStartX;
      lastTouchY = touchStartY;
      startOffsetX = $offsetX;
      startOffsetY = $offsetY;
    }
  }
  
  function handleTouchMove(e: TouchEvent) {
    // Check if touch started on an event node
    const isOnEventNode = !!touchTarget?.closest('.event-node');
    
    // Only prevent default if not on an event node
    if (!isOnEventNode) {
      e.preventDefault();
    }
    
    if (!isTouching) return;
    
    // If we've moved more than a small threshold, mark as moved
    if (e.touches.length === 1) {
      const dx = e.touches[0].clientX - touchStartX;
      const dy = e.touches[0].clientY - touchStartY;
      const distance = Math.sqrt(dx * dx + dy * dy);
      
      // If moved more than 10px, consider it a drag not a tap
      if (distance > 10) {
        touchMoved = true;
        
        // Don't pan if we started on an event node
        if (isOnEventNode) {
          return;
        }
      }
    }
    
    if (e.touches.length === 1 && !isMultiTouch && !isOnEventNode) {
      // Single touch - pan/drag (only if not on an event node)
      const touchX = e.touches[0].clientX;
      const touchY = e.touches[0].clientY;
      
      // Calculate delta from last position
      const deltaX = touchX - lastTouchX;
      const deltaY = touchY - lastTouchY;
      
      // Update offsets without animation during touch
      offsetX.set($offsetX + deltaX);
      offsetY.set($offsetY + deltaY);
      
      // Store current touch position
      lastTouchX = touchX;
      lastTouchY = touchY;
    } else if (e.touches.length === 2) {
      touchMoved = true;
      
      // Two touches - pinch zoom
      const touch1 = e.touches[0];
      const touch2 = e.touches[1];
      
      // Calculate current distance
      const currentDistance = Math.hypot(
        touch2.clientX - touch1.clientX,
        touch2.clientY - touch1.clientY
      );
      
      // Calculate the zoom factor based on the change in distance
      const zoomDelta = currentDistance / touchDistance;
      
      // Apply zoom with scaling limits from config
      if (zoomDelta !== 1) {
        const newScale = Math.max(
          defaultTimelineViewConfig.minZoom, 
          Math.min(defaultTimelineViewConfig.maxZoom, $scale * zoomDelta)
        );
        scale.set(newScale);
        touchDistance = currentDistance;
      }
      
      // Handle panning during pinch zoom
      const currentMidX = (touch1.clientX + touch2.clientX) / 2;
      const currentMidY = (touch1.clientY + touch2.clientY) / 2;
      
      // Calculate delta from last midpoint
      const deltaX = currentMidX - lastTouchX;
      const deltaY = currentMidY - lastTouchY;
      
      // Update offsets without animation during touch
      offsetX.set($offsetX + deltaX);
      offsetY.set($offsetY + deltaY);
      
      // Store current midpoint
      lastTouchX = currentMidX;
      lastTouchY = currentMidY;
    }
  }
  
  function handleTouchEnd(e: TouchEvent) {
    // Check if this was a tap (short duration, little movement)
    const touchDuration = Date.now() - touchStartTime;
    const wasTap = !touchMoved && touchDuration < 300;
    const currentTime = Date.now();
    
    // If it was a tap and we have a target, handle it
    if (wasTap && touchTarget) {
      // Check if we tapped on an event node
      const eventNode = touchTarget.closest('.event-node');
      
      if (eventNode) {
        // Get the event slug from the data attribute
        const slug = eventNode.getAttribute('data-slug');
        if (slug) {
          // Find the corresponding event
          const event = events.find(evt => evt.slug === slug);
          if (event) {
            e.preventDefault(); // Prevent any default browser handling
            
            // Check if this is the same event that's already selected
            if (selectedEvent && selectedEvent.slug === slug) {
              // Double tap/click detection - only navigate if we're tapping an already selected event
              // Allow 1000ms between taps for double-tap
              if (currentTime - lastTapTime < 2000) {
                console.log('Double-tap detected, navigating to:', slug);
                navigateToPost(slug);
              }
              
              // Update the last tap time even for single taps
              lastTapTime = currentTime;
            } else {
              // First tap on this event - just select it
              console.log('First tap on event, selecting:', slug);
              selectedEvent = event;
              dispatch('select', { event });
              lastTapTime = currentTime;
            }
          }
        }
      } else if (touchTarget === timelineContainer || touchTarget.classList.contains('timeline-container')) {
        // Tap on background - deselect current selection if any
        if (selectedEvent) {
          console.log('Tap on background, deselecting');
          selectedEvent = null;
          hoveredEvent = null;
          dispatch('deselect');
        }
      }
    }
    
    // Reset touch target
    touchTarget = null;
    
    // Check if there are still touches active
    if (e.touches.length === 0) {
      isTouching = false;
      isMultiTouch = false;
      
      // Remove dragging class
      if (timelineContainer) {
        timelineContainer.classList.remove('dragging');
      }
      
      // Restore normal animations with a slight delay
      // This gives a nice smooth settling effect
      setTimeout(() => {
        setTouchMode(false);
      }, 50);
    } else if (e.touches.length === 1) {
      // Transition from pinch to pan
      isMultiTouch = false;
      touchStartX = e.touches[0].clientX;
      touchStartY = e.touches[0].clientY;
      lastTouchX = touchStartX;
      lastTouchY = touchStartY;
      startOffsetX = $offsetX;
      startOffsetY = $offsetY;
    }
  }
  
  // Check if we're in mobile view
  function checkMobileView() {
    isMobile = window.innerWidth < 768; // Standard mobile breakpoint
    handleResize();
  }
  
  // Set up and tear down event listeners
  onMount(() => {
    if (timelineContainer) {
      // Set up direct DOM event handlers
      setupDirectEventHandlers();
      
      // Add touch event listeners
      timelineContainer.addEventListener('touchstart', handleTouchStart, { passive: false });
      timelineContainer.addEventListener('touchmove', handleTouchMove, { passive: false });
      timelineContainer.addEventListener('touchend', handleTouchEnd);
      timelineContainer.addEventListener('touchcancel', handleTouchEnd);
      // Add double-click handler for desktop zoom
      timelineContainer.addEventListener('dblclick', handleDoubleClick);
      
      // Add orientation change listener
      window.addEventListener('orientationchange', () => {
        // Show fade overlay during orientation change
        fadeOverlayVisible = true;
        
        // After orientation change completes, hide overlay
        setTimeout(() => {
          fadeOverlayVisible = false;
        }, 600); // Slightly longer than the CSS transition
      });
    }

    setTimeout(() => {
      if (events.length > 0 && typeof window !== 'undefined') {
        const path = window.location.pathname;
        if (path.includes('/posts/')) {
          const slug = path.split('/posts/')[1].replace(/\/$/, '');
          console.log(`Current page slug: ${slug}`);
          
          // Find matching event
          const event = events.find(e => slug.includes(e.slug));
          if (event) {
            console.log(`Auto-selecting event: ${event.title}`);
            selectedEvent = event;
            dispatch('select', { event });
          }
        }
      }
    }, 500); // Short delay to ensure everything is loaded
    
    // Check mobile view
    checkMobileView();
    
    // Attach global mouse event handlers
    window.addEventListener('mousemove', drag);
    window.addEventListener('mouseup', endDrag);
    
    // Initial resize
    handleResize();
    
    // Handle resize events
    window.addEventListener('resize', () => {
      checkMobileView();
      handleResize();
    });
    
    // Expose the control functions to the global scope
    if (typeof window !== 'undefined') {
      window.timelineControls = window.timelineControls || {};
      window.timelineControls.zoomIn = zoomIn;
      window.timelineControls.zoomOut = zoomOut;
      window.timelineControls.resetView = resetView;
      window.timelineControls.pan = pan;
    }
    
    // Fade in the content after initial load
    setTimeout(() => {
      fadeOverlayVisible = false;
    }, 300);
    
    return () => {
      window.removeEventListener('mousemove', drag);
      window.removeEventListener('mouseup', endDrag);
      window.removeEventListener('resize', handleResize);
      window.removeEventListener('orientationchange', () => {});
      
      if (timelineContainer) {
        timelineContainer.removeEventListener('touchstart', handleTouchStart);
        timelineContainer.removeEventListener('touchmove', handleTouchMove);
        timelineContainer.removeEventListener('touchend', handleTouchEnd);
        timelineContainer.removeEventListener('touchcancel', handleTouchEnd);
        timelineContainer.removeEventListener('dblclick', handleDoubleClick);
      }
    };
  });
  
  // Handle window resize
  function handleResize() {
    if (timelineContainer) {
      containerWidth = timelineContainer.offsetWidth;
      containerHeight = timelineContainer.offsetHeight;
    }
  }
  
  // Reset state when component updates
  onDestroy(() => {
    selectedEvent = null;
    hoveredEvent = null;
    
    // Clear any pending hover timeout
    if (hoverTimeoutId) {
      clearTimeout(hoverTimeoutId);
      hoverTimeoutId = null;
    }
  });
  
  // Update functions exposed to parent components with config values
  export function zoomIn() {
    scale.update(s => Math.min(
      defaultTimelineViewConfig.maxZoom, 
      s + defaultTimelineViewConfig.zoomStep
    ));
  }
  
  export function zoomOut() {
    scale.update(s => Math.max(
      defaultTimelineViewConfig.minZoom, 
      s - defaultTimelineViewConfig.zoomStep
    ));
  }
  
  // Simplified background update function
  export function updateBackground(newBackground: string) {
    if (newBackground && newBackground !== background) {
      console.log(`Background changed to: ${newBackground}`);
      background = newBackground;
    }
  }
  
  export function resetView() {
    scale.set(defaultTimelineViewConfig.defaultZoom);
    offsetX.set(0);
    offsetY.set(0);
    selectedEvent = null;
  }
  
  export function pan(deltaX: number, deltaY: number) {
    offsetX.update(x => x + deltaX);
    offsetY.update(y => y + deltaY);
  }

  // Export getter methods to access the current state
  export function getCurrentScale(): number {
    return $scale;
  }

  export function getCurrentOffsetX(): number {
    return $offsetX;
  }

  export function getCurrentOffsetY(): number {
    return $offsetY;
  }
  
  $: backgroundTransform = `scale(${1.05 + 0.05 * $scale}) translate(${-$offsetX * 0.05}px, ${-$offsetY * 0.05}px) ${isMobile ? 'scale(1.2)' : ''}`;


  export function panToYear(targetYear: number) {
    // Only proceed if we have valid dimensions and data
    if (!containerWidth || !containerHeight || !timespan || timespan === 0) {
      console.warn("Cannot pan: missing dimensions", { containerWidth, containerHeight, timespan });
      return;
    }
    
    // Calculate raw percentage (without any padding)
    const rawPercentage = ((targetYear - (startYear || 0)) / timespan) * 100;
    
    console.log(`Panning to year ${targetYear}:`, {
      rawPercentage: rawPercentage.toFixed(2) + "%",
      timespan,
      startYear,
      endYear,
      scale: $scale.toFixed(2)
    });
    
    // Simply remove the entire if/else structure and just keep the horizontal panning code:
    const targetPosition = (containerWidth * rawPercentage) / 100;
    const viewportCenter = containerWidth / 2;
    const requiredOffset = viewportCenter - targetPosition;

    console.log(`Panning:`, {
      targetPosition: targetPosition.toFixed(1) + "px",
      viewportCenter: viewportCenter.toFixed(1) + "px",
      requiredOffset: requiredOffset.toFixed(1) + "px",
      scaledOffset: (requiredOffset / $scale).toFixed(1) + "px"
    });

    // Apply the offset (adjusted for scale)
    offsetX.set(requiredOffset / $scale);
  }

  // Method to set position directly (used for restoring saved positions)
  export function setPosition(newScale: number, newOffsetX: number, newOffsetY: number) {
    // Validate input values to avoid invalid states
    if (isNaN(newScale) || isNaN(newOffsetX) || isNaN(newOffsetY)) {
      console.error("Invalid position values:", { newScale, newOffsetX, newOffsetY });
      return;
    }
    
    // Clamp scale to valid range 
    const clampedScale = Math.max(0.5, Math.min(5, newScale));
    
    // Apply values
    scale.set(clampedScale);
    offsetX.set(newOffsetX);
    offsetY.set(newOffsetY);
    
    console.log("Position set to:", { 
      scale: clampedScale, 
      offsetX: newOffsetX, 
      offsetY: newOffsetY 
    });
  }

  export function navigateToEraRange(eraStartYear: number, eraEndYear: number) {
    const jitter = Math.random() * 0.05;
    if (!eraStartYear || !eraEndYear) {
      console.warn("Invalid era range:", eraStartYear, eraEndYear);
      return;
    }
    
    // Find the era configuration for the given range
    let eraConfig = null;
    const eraConfigs = extractEraConfig(events);
    
    // Look for an era that matches these exact start/end years
    for (const [eraKey, config] of Object.entries(eraConfigs)) {
      if (config.startYear === eraStartYear && config.endYear === eraEndYear) {
        eraConfig = config;
        console.log(`Found exact era config for ${eraKey}:`, eraConfig);
        break;
      }
    }
    
    // If we didn't find an exact match, do a second pass to find a containing era
    if (!eraConfig) {
      for (const [eraKey, config] of Object.entries(eraConfigs)) {
        if (eraStartYear >= config.startYear && eraEndYear <= config.endYear) {
          eraConfig = config;
          console.log(`Found containing era config for ${eraKey}:`, eraConfig);
          break;
        }
      }
    }
    
    // Calculate the middle of the era as default focus point
    const midYear = Math.floor((eraStartYear + eraEndYear) / 2);
    console.log(`Era range: ${eraStartYear}-${eraEndYear}, midpoint: ${midYear}`);
    
    // Determine zoom level - use configuration if available
    let targetZoom;
    const yearToCenter = eraConfig?.panToYear || midYear;
    
    if (eraConfig?.zoomLevel !== undefined) {
      // Use the custom zoom level from config
      targetZoom = eraConfig.zoomLevel;
      console.log(`Using configured zoom level: ${targetZoom}`);
    } else {
      // Calculate based on general rules using thresholds from config
      const viewConfig = defaultTimelineViewConfig;
      const eraSpan = eraEndYear - eraStartYear;
      const fullTimespan = (endYear || 2100) - (startYear || 2000);
      const zoomRatio = fullTimespan / eraSpan;
      
      // Determine zoom level based on thresholds
      if (zoomRatio > viewConfig.zoomRatioThresholds.verySmall) {
        targetZoom = viewConfig.zoomLevels.verySmall;
      } else if (zoomRatio > viewConfig.zoomRatioThresholds.small) {
        targetZoom = viewConfig.zoomLevels.small;
      } else if (zoomRatio > viewConfig.zoomRatioThresholds.medium) {
        targetZoom = viewConfig.zoomLevels.medium;
      } else if (zoomRatio > viewConfig.zoomRatioThresholds.large) {
        targetZoom = viewConfig.zoomLevels.large;
      } else if (zoomRatio > viewConfig.zoomRatioThresholds.veryLarge) {
        targetZoom = viewConfig.zoomLevels.veryLarge;
      } else {
        targetZoom = viewConfig.zoomLevels.full;
      }
      
      console.log(`Calculated zoom level: ${targetZoom} (ratio: ${zoomRatio.toFixed(2)})`);
    }
    
    // Clamp zoom to valid range
    targetZoom = Math.max(defaultTimelineViewConfig.minZoom, 
                         Math.min(defaultTimelineViewConfig.maxZoom, targetZoom));
    
    // Reset view first for a clean start
    resetView();
    
    // Apply zoom and pan after a short delay to allow reset to complete
    setTimeout(() => {
      // Set zoom level
      scale.set(targetZoom + (eraStartYear === 1 ? jitter : 0));
      
      // Then pan to the specified year or midpoint
      panToYear(yearToCenter);
      
      console.log(`Timeline positioned at year ${yearToCenter} with zoom ${targetZoom}`);
    }, 300);
  }
</script>

<div class="card-base relative overflow-hidden {asBanner ? 'h-full rounded-none' : 'h-[300px] md:h-[300px]'} {compact ? 'compact-mode' : ''}" 
     data-start-year={startYear} 
     data-end-year={endYear}>

  <!-- Fade overlay for transitions -->
  {#if fadeOverlayVisible || isNavigating}
    <div class="fade-overlay absolute inset-0 bg-black z-50 {fadeOverlayVisible ? 'opacity-100' : 'opacity-0'}" 
         style="transition: opacity 400ms ease-in-out;"></div>
  {/if}

  <!-- Simple background without any transition logic -->
  <div class="absolute inset-0 z-0 overflow-hidden">
    <img 
      src={background} 
      alt="Timeline background" 
      class="w-full h-full object-cover"
      style="transform: {backgroundTransform};"
    />
    <div class="absolute inset-0 bg-gradient-to-r from-[oklch(0.25_0.05_var(--hue))] to-[oklch(0.15_0.05_var(--hue))] opacity-20 dark:opacity-20 backdrop-blur-[2px]"></div>
  </div>
  
  <!-- Starfield effect -->
  <div class="absolute inset-0 z-0">
    <div class="w-full h-full starfield-overlay"></div>
  </div>
  
  <!-- Timeline container -->
  <div class="timeline-container relative z-10 w-full h-full cursor-grab active:cursor-grabbing {isTouchActive ? 'touch-active' : ''}"
       bind:this={timelineContainer}
       on:mousedown={startDrag}
       role="application"
       aria-label="Interactive timeline visualization"
       tabindex="0"
       style="transform: scale({$scale}) translate({$offsetX/$scale}px, {$offsetY/$scale}px);">
    
    <!-- Center line - horizontal for desktop, vertical for mobile -->
    <div class="timeline-center-line absolute w-full h-[2px] top-1/2 bg-gradient-to-r from-transparent via-[oklch(0.7_0.08_var(--hue))] to-transparent opacity-10"></div>
    
    <!-- Year markers -->
    <div class="timeline-start-marker absolute left-[15%] w-[4px] top-[40%] bottom-[60%] bg-[oklch(0.7_0.2_var(--hue))] opacity-60 rounded-full"></div>
    <div class="timeline-end-marker absolute right-[15%] w-[4px] top-[40%] bottom-[60%] bg-[oklch(0.7_0.2_var(--hue))] opacity-60 rounded-full"></div>

    <!-- Events -->
    {#each eventPositions as { event, timelinePosition, offsetPosition, floatClass, shouldFloat }, i (event.slug + '-' + useEraColors)}
    <div 
      class="timeline-event absolute {isMobile ? 'timeline-event-mobile' : 'timeline-event-desktop'} {!isMobile && shouldFloat ? floatClass : ''}"
      style={`left: ${timelinePosition}%; top: 50%; transform: translate(0, ${offsetPosition}px) scale(${1/$scale});`}
    >
        <!-- Star node with data attributes for DOM event handling -->
        <div 
          class="event-node absolute transform -translate-x-1/2 -translate-y-1/2 cursor-pointer"
          data-slug={event.slug}
          data-year={event.year}
          data-era={event.era}
        >
          <StarNode 
            era={event.era} 
            isKeyEvent={event.isKeyEvent} 
            isSelected={selectedEvent?.slug === event.slug}
            isHovered={hoveredEvent?.slug === event.slug}
            size={event.isKeyEvent ? 5 : 4}
            identifier={event.slug}
            {useEraColors}
          />
        </div>
        
        <!-- Only show card if this event is selected or hovered AND NOT in mobile mode -->
        {#if (selectedEvent?.slug === event.slug || hoveredEvent?.slug === event.slug) && !isMobile}
          <div class="card-wrapper" style="transform: scale({1/$scale});">
            <TimelineCard 
              {event} 
              isSelected={selectedEvent?.slug === event.slug}
              compact={compact}
              position={offsetPosition < 0 ? 'top' : 'bottom'}
              isMobile={false}
            />
          </div>
        {/if}
      </div>
    {/each}
  </div>
  
  <!-- Fixed mobile card container - now uses fixed positioning instead of being inside the scrollable area -->
  {#if isMobile && (selectedEvent || hoveredEvent)}
    <div class="fixed-mobile-card-container">
      <!-- Keep mobile card but position it below the timeline point -->
      <TimelineCard 
        event={selectedEvent || hoveredEvent}
        isSelected={!!selectedEvent}
        {compact}
        position="bottom"
        isMobile={true}
      />
    </div>
  {/if}
  
  <!-- Empty state -->
  {#if events.length === 0}
    <div class="flex flex-col items-center justify-center py-10 text-center">
      <div class="text-6xl text-[var(--primary)] mb-4">
        <svg viewBox="0 0 24 24" class="w-16 h-16">
          <path d="M12 2L15.09 8.26L22 9.27L17 14.14L18.18 21.02L12 17.77L5.82 21.02L7 14.14L2 9.27L8.91 8.26L12 2Z" 
                fill="currentColor" stroke="white" stroke-width="1" />
        </svg>
      </div>
      <div class="text-75 font-bold">No timeline events found</div>
      <div class="text-50 text-sm mt-2">
        Add timelineYear property to your post frontmatter to create timeline events
      </div>
      <div class="card-base bg-[var(--btn-plain-bg-hover)] p-4 mt-4 max-w-md">
        <code class="text-xs">
          ---<br>
          title: "My Timeline Event"<br>
          timelineYear: 2025<br>
          timelineEra: "your-era"<br>
          isKeyEvent: true<br>
          ---
        </code>
      </div>
    </div>
  {/if}
</div>

<style>
  /* Optimization for mobile */
  @media (max-width: 767px) {
    .timeline-container {
      will-change: transform;
      backface-visibility: hidden;
    }
    
    .timeline-event {
      will-change: transform;
    }
    
    /* Fix flickering on iOS */
    .fixed-mobile-card-container {
      transform: translateZ(0);
    }
  }
  
  /* During touch, make transitions immediate */
  .touch-active {
    transition: none !important;
  }
  
  .touch-active * {
    transition: none !important;
  }
  
  /* Prevent outline on focus */
  .timeline-container:focus {
    outline: none;
  }
  
  /* Add smooth transition for timeline cards (for hover delay) */
  :global(.timeline-card) {
    transition: opacity 0.2s ease-in, transform 0.25s ease-out;
  }

  /* Add floating animation classes */
  .floating-animation-1 {
    animation: float1 35s infinite ease-in-out;
  }

  .floating-animation-2 {
    animation: float2 40s infinite ease-in-out;
    animation-delay: -8s;
  }

  .floating-animation-3 {
    animation: float3 45s infinite ease-in-out;
    animation-delay: -15s;
  }

  .floating-animation-4 {
    animation: float4 50s infinite ease-in-out;
    animation-delay: -22s;
  }

  .floating-animation-5 {
    animation: float5 55s infinite ease-in-out;
    animation-delay: -30s;
  }

  /* Keyframes with larger Y movements */
  @keyframes float1 {
    0%, 100% { transform: translateY(0px); }
    50% { transform: translateY(44px); }
  }

  @keyframes float2 {
    0%, 100% { transform: translateY(0px); }
    50% { transform: translateY(-60px); }
  }

  @keyframes float3 {
    0%, 100% { transform: translateY(0px); }
    50% { transform: translateY(52px); }
  }

  @keyframes float4 {
    0%, 100% { transform: translateY(0px); }
    50% { transform: translateY(-48px); }
  }

  @keyframes float5 {
    0%, 100% { transform: translateY(0px); }
    50% { transform: translateY(36px); }
  }
</style>