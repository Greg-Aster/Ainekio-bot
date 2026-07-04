<script lang="ts">
  import { onMount, onDestroy, createEventDispatcher } from 'svelte';
  import { timelineStore, timelineActions, filteredEvents, selectedEvent } from '../../stores/timelineStore';
  import type { TimelineEvent } from '../../services/TimelineService.client';
  import { extractEraConfig } from '../../services/TimelineService.client'; // Added this import
  
  // Components
  import TimelineCore from './TimelineCore.svelte';
  import ListView from './TimelineViewModes/ListView.svelte';
  import MapView from './TimelineViewModes/MapView.svelte';
  import TreeView from './TimelineViewModes/TreeView.svelte';
  
  // Props
  export let id: string = "timeline-controller";
  export let category: string = "";
  export let startYear: number | undefined = undefined;
  export let endYear: number | undefined = undefined;
  export let background: string = "/assets/banner/0001.png";
  export let compact: boolean = false;
  export let asBanner: boolean = false;
  export let bannerHeight: string = "500px";
  export let initialEvents: string = "[]"; // Serialized events

  // Local state
  let timelineCore: TimelineCore;
  let loading = true;
  let error: string | null = null;
  let eraConfig = {};
  let isInitialized = false;
  let isMobile = false;
  let showGestureHint = false;
  let gestureHintTimer: number | null = null;

  // Safe Event dispatch
  const dispatch = createEventDispatcher();
  
  // Simple safe JSON parse function that doesn't use complex revivers
  function parseEvents(jsonString: string): any[] {
    if (!jsonString || typeof jsonString !== 'string') {
      return [];
    }
    
    try {
      const parsed = JSON.parse(jsonString);
      return Array.isArray(parsed) ? parsed : [];
    } catch (e) {
      console.error("Error parsing events:", e);
      return [];
    }
  }
  
  // Check if we're on a mobile device
  function checkMobileView() {
    isMobile = window.innerWidth < 768; // Standard mobile breakpoint
  }
  
  // Function to show gesture hint for mobile users
  function showTouchGestureHint() {
    // Only show hint on mobile devices
    if (!isMobile) return;
    
    // Set flag to show the hint
    showGestureHint = true;
    
    // Clear any existing timer
    if (gestureHintTimer) {
      clearTimeout(gestureHintTimer);
    }
    
    // Set timer to hide the hint after 3 seconds
    gestureHintTimer = setTimeout(() => {
      showGestureHint = false;
      gestureHintTimer = null;
    }, 3000) as unknown as number;
  }
  
  // New function to initialize timeline with saved era
  function initializeTimeline() {
    // 1. Get the current configuration
    const availableEras = Object.keys(eraConfig);
    const savedEra = $timelineStore.era || $timelineStore.lastEra;
    
    console.log("Available eras:", availableEras);
    console.log("Saved era:", savedEra);
    
    // 2. Validate the era
    const isValidEra = savedEra && availableEras.includes(savedEra);
    
    // 3. Set the dropdown value (UI state)
    const eraSelect = document.querySelector('.era-select') as HTMLSelectElement;
    if (eraSelect) {
      eraSelect.value = isValidEra ? savedEra : 'all';
    }
    
    // 4. Apply the navigation
    if (isValidEra && timelineCore) {
      // If we have saved position data for this era, use it
      if ($timelineStore.lastEraScale !== null && 
          $timelineStore.lastEraOffsetX !== null && 
          $timelineStore.lastEraOffsetY !== null) {
        console.log('Restoring saved position', {
          scale: $timelineStore.lastEraScale,
          offsetX: $timelineStore.lastEraOffsetX,
          offsetY: $timelineStore.lastEraOffsetY
        });
        timelineCore.setPosition(
          $timelineStore.lastEraScale, 
          $timelineStore.lastEraOffsetX, 
          $timelineStore.lastEraOffsetY
        );
      } else {
        // Otherwise navigate to the era's range
        const config = eraConfig[savedEra];
        console.log(`Navigating to era range: ${config.startYear}-${config.endYear}`);
        timelineCore.navigateToEraRange(config.startYear, config.endYear);
      }
    } else {
      // Default to 'all' view
      console.log("No valid era found, using default 'all' view");
      if (timelineCore) {
        timelineCore.resetView();
      }
      // Update the store if needed
      if (savedEra && !isValidEra) {
        console.log(`Clearing invalid era: ${savedEra}`);
        timelineActions.setEra(null);
      }
    }
  }
  
// Initialize the component only after mounting
onMount(() => {
  console.log("Timeline controller mounting");
  
  // Check for mobile view
  checkMobileView();
  
  // Listen for window resize to update mobile state
  window.addEventListener('resize', checkMobileView);
  
  // Show gesture hint for mobile users
  if (isMobile) {
    // Show gesture hint with a slight delay to ensure it appears after the component is visible
    setTimeout(showTouchGestureHint, 1000);
  }
  
  // Avoid double initialization
  if (isInitialized) return;

  try {
    // Parse events first
    const events = parseEvents(initialEvents);
    
    // Process events (ensure year is a number)
    const processedEvents = events.map(event => ({
      ...event,
      year: typeof event.year === 'string' ? parseInt(event.year, 10) : event.year
    }));
    
    // Initialize store props
    if (category) {
      timelineActions.setCategory(category);
    }
    
    if (asBanner) {
      timelineActions.setBannerMode(true);
    }
    
    if (startYear || endYear) {
      timelineActions.setYearRange(
        startYear || null,
        endYear || null
      );
    }
    
    if (compact) {
      timelineActions.toggleCompact();
    }
    
    // Set initial events
    timelineActions.setInitialEvents(processedEvents);
    
    // Extract era configuration properly using the utility function
    eraConfig = extractEraConfig(processedEvents);
    
    // Create a function to determine the appropriate background based on priority
    function determineBackground() {
      // First priority: Check for event-specific backgrounds from blog posts
      const backgroundEvents = processedEvents.filter(event => event.bannerData?.background);
      if (backgroundEvents.length > 0 && backgroundEvents[0].bannerData?.background) {
        console.log("Using banner post background:", backgroundEvents[0].bannerData.background);
        return backgroundEvents[0].bannerData.background;
      }
      
      // Second priority: Use the current era's background
      const currentEra = $timelineStore.era || $timelineStore.lastEra || 'all-eras';
      if (eraConfig[currentEra]?.backgroundImage) {
        console.log("Using era background:", eraConfig[currentEra].backgroundImage);
        return eraConfig[currentEra].backgroundImage;
      }
      
      // Fallback: Use the default background
      console.log("Using default background:", background);
      return background; // this is the prop from the component
    }

    // Set the background based on priority
    const selectedBackground = determineBackground();
    timelineActions.setBackground(selectedBackground);
    
    // Mark as initialized
    isInitialized = true;
    
    // Initialize timeline with proper era after a short delay
    // to ensure timelineCore is ready
    setTimeout(() => {
      if (timelineCore) {
        console.log("TimelineCore is ready, initializing timeline");
        initializeTimeline();
      } else {
        console.log("TimelineCore not ready yet, setting up interval check");
        // If timeline core isn't ready yet, wait for it
        const checkInterval = setInterval(() => {
          if (timelineCore) {
            console.log("TimelineCore is now ready, initializing timeline");
            initializeTimeline();
            clearInterval(checkInterval);
          }
        }, 100);
        
        // Clear interval after max 2 seconds to prevent infinite loop
        setTimeout(() => clearInterval(checkInterval), 2000);
      }
    }, 100);
    
  } catch (e) {
    console.error("Error initializing timeline:", e);
    error = "Failed to initialize timeline";
  } finally {
    // Always set loading to false, even if there's an error
    loading = false;
  }
  
  // Return cleanup function
  return () => {
    window.removeEventListener('resize', checkMobileView);
    if (gestureHintTimer) {
      clearTimeout(gestureHintTimer);
    }
  };
});
  
// Improved handleEraFilter function with background handling
function handleEraFilter(e) {
  const value = e.target.value;
  console.log(`Era selected from dropdown: ${value}`);
  
  // Handle "all" or "all-time" options more directly
  if (value === 'all') {
    console.log(`Setting view for "All Eras" option`);
    timelineActions.setEra('all-eras');
    
    // Set the background for all-eras (with improved handling)
    if (eraConfig['all-eras'] && eraConfig['all-eras'].backgroundImage) {
      // Update the store
      timelineActions.setBackground(eraConfig['all-eras'].backgroundImage);
      // Force update on TimelineCore by directly updating the prop
      if (timelineCore) timelineCore.updateBackground(eraConfig['all-eras'].backgroundImage);
    }
    
    if (timelineCore && typeof timelineCore.navigateToEraRange === 'function') {
      timelineCore.navigateToEraRange(eraConfig['all-eras'].startYear, eraConfig['all-eras'].endYear);
    } else {
      handleResetView();
    }
    return;
  } else if (value === 'all-time') {
    console.log(`Setting view for "All Time" option`);
    timelineActions.setEra('all-time');
    
    // Set the background for all-time (with improved handling)
    if (eraConfig['all-time'] && eraConfig['all-time'].backgroundImage) {
      // Update the store
      timelineActions.setBackground(eraConfig['all-time'].backgroundImage);
      // Force update on TimelineCore by directly updating the prop
      if (timelineCore) timelineCore.updateBackground(eraConfig['all-time'].backgroundImage);
    }
    
    if (timelineCore && typeof timelineCore.navigateToEraRange === 'function') {
      timelineCore.navigateToEraRange(eraConfig['all-time'].startYear, eraConfig['all-time'].endYear);
    } else {
      handleResetView();
    }
    return;
  }
  
  // Validate era exists in config
  if (!eraConfig[value]) {
    console.warn(`Invalid era selected: ${value}`);
    e.target.value = 'all'; // Reset dropdown to "all"
    timelineActions.setEra(null);
    handleResetView();
    return;
  }
  
  // For specific era selection
  const startYear = eraConfig[value].startYear;
  const endYear = eraConfig[value].endYear;
  
  console.log(`Era selected: ${value} (${startYear}-${endYear})`);
  
  // Update the era in the store (this will persist to localStorage)
  timelineActions.setEra(value);
  
  // Check if we should update the background
  let shouldUpdateBackground = true;
  
  // Check if any event has a specific background (higher priority)
  const eventsInEra = $filteredEvents.filter(e => 
    e.year >= startYear && e.year <= endYear && e.bannerData?.background
  );
  
  if (eventsInEra.length > 0 && eventsInEra[0].bannerData?.background) {
    // If an event has a specific background, use it
    const eventBackground = eventsInEra[0].bannerData.background;
    console.log(`Using event-specific background: ${eventBackground}`);
    timelineActions.setBackground(eventBackground);
    if (timelineCore) timelineCore.updateBackground(eventBackground);
    shouldUpdateBackground = false;
  }
  
  // Only use era background if no event-specific background was found
  if (shouldUpdateBackground && eraConfig[value].backgroundImage) {
    console.log(`Setting era background image: ${eraConfig[value].backgroundImage}`);
    timelineActions.setBackground(eraConfig[value].backgroundImage);
    if (timelineCore) timelineCore.updateBackground(eraConfig[value].backgroundImage);
  }
  
  // Call the navigateToEraRange function if it exists
  if (timelineCore && typeof timelineCore.navigateToEraRange === 'function') {
    timelineCore.navigateToEraRange(startYear, endYear);
    
    // After navigation is complete, save the position for this era
    // We'll add a delay to ensure the animation has time to complete
    setTimeout(() => {
      if (timelineCore) {
        // Save the current position for this era
        timelineActions.saveEraPosition(
          timelineCore.getCurrentScale(), 
          timelineCore.getCurrentOffsetX(), 
          timelineCore.getCurrentOffsetY()
        );
      }
    }, 500);
  } else {
    console.warn("timelineCore.navigateToEraRange function not available");
    handleResetView(); // Fallback to reset view
  }
}
  
  function handleResize() {
    // Simple resize handler
    checkMobileView();
  }

  // Safe handlers for timeline actions
  function handleZoomIn() {
    timelineActions.zoomIn();
    if (timelineCore && typeof timelineCore.zoomIn === 'function') {
      timelineCore.zoomIn();
      
      // Save position after zoom
      setTimeout(() => {
        if (timelineCore && $timelineStore.era) {
          timelineActions.saveEraPosition(
            timelineCore.getCurrentScale(),
            timelineCore.getCurrentOffsetX(),
            timelineCore.getCurrentOffsetY()
          );
        }
      }, 300);
    }
  }
  
  function handleZoomOut() {
    timelineActions.zoomOut();
    if (timelineCore && typeof timelineCore.zoomOut === 'function') {
      timelineCore.zoomOut();
      
      // Save position after zoom
      setTimeout(() => {
        if (timelineCore && $timelineStore.era) {
          timelineActions.saveEraPosition(
            timelineCore.getCurrentScale(),
            timelineCore.getCurrentOffsetX(),
            timelineCore.getCurrentOffsetY()
          );
        }
      }, 300);
    }
  }
  
  function handlePan(x: number, y: number) {
    timelineActions.pan(x, y);
    if (timelineCore && typeof timelineCore.pan === 'function') {
      timelineCore.pan(x, y);
      
      // Save position after pan
      setTimeout(() => {
        if (timelineCore && $timelineStore.era) {
          timelineActions.saveEraPosition(
            timelineCore.getCurrentScale(),
            timelineCore.getCurrentOffsetX(),
            timelineCore.getCurrentOffsetY()
          );
        }
      }, 300);
    }
  }
  
  function handleResetView() {
    timelineActions.resetView();
    if (timelineCore && typeof timelineCore.resetView === 'function') {
      timelineCore.resetView();
    }
  }
  
  function handleSelectEvent(e) {
    if (e && e.detail && e.detail.event && e.detail.event.slug) {
      timelineActions.selectEvent(e.detail.event.slug);
    }
  }
  
  function handleDeselectEvent() {
    timelineActions.selectEvent(null);
  }
  
  function handleSetViewMode(mode) {
    timelineActions.setViewMode(mode);
  }
  
  // Keep the function even though we removed the buttons
  function handleToggleCompact() {
    timelineActions.toggleCompact();
  }
  
  // Define currentHeight as a reactive variable
  $: currentHeight = asBanner ? (isMobile ? '600px' : bannerHeight) : "500px";
  $: useEraColors = $timelineStore.era === 'all-eras';

  // (like $: currentHeight = asBanner ? ... and $: useEraColors = ...)
$: if (timelineCore && $timelineStore.background) {
  // Ensure the TimelineCore background stays in sync with the store
  timelineCore.updateBackground($timelineStore.background);
}

</script>

<div class="timeline-wrapper relative w-full overflow-hidden {asBanner ? 'timeline-banner-mode' : ''}" 
     style="height: {currentHeight};" 
     {id}
     on:timeline:resize={handleResize}>
  
  <!-- Main content container that takes the full area -->
  <div class="relative w-full h-full">
    <!-- Main content area with different views - takes up the entire space -->
    <div class="timeline-viewport w-full h-full overflow-hidden cursor-grab active:cursor-grabbing">
      <!-- Loading state -->
      {#if loading}
        <div class="absolute inset-0 flex items-center justify-center bg-white/80 dark:bg-black/50 z-[100]">
          <div class="animate-spin rounded-full h-12 w-12 border-b-2 border-[var(--primary)]"></div>
        </div>
      {/if}
      
      <!-- Error state -->
      {#if error}
        <div class="absolute inset-0 flex items-center justify-center bg-white/90 dark:bg-black/70 z-[100]">
          <div class="text-center p-4">
            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-12 h-12 text-red-500 mx-auto mb-2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z" />
            </svg>
            <h3 class="text-lg font-bold text-white">Error loading timeline</h3>
            <p class="text-sm text-white/80">{error}</p>
            <button on:click={() => window.location.reload()}
                    class="mt-3 bg-[var(--primary)] text-white px-4 py-2 rounded-md text-sm">
              Retry
            </button>
          </div>
        </div>
      {/if}
      
    <!-- Timeline View -->
    <div class="w-full h-full {$timelineStore.viewMode !== 'timeline' ? 'hidden' : ''}">
      <TimelineCore
      bind:this={timelineCore}
      events={$filteredEvents}
      {startYear}
      {endYear}
      background={$timelineStore.background}
      compact={$timelineStore.compact}
      {asBanner}
      {useEraColors}
      on:select={handleSelectEvent}
      on:deselect={handleDeselectEvent}
    />
    </div>
      
      <!-- List View -->
      <div class="timeline-view pt-4 relative {$timelineStore.viewMode !== 'list' ? 'hidden' : ''}">
        <ListView 
          events={$filteredEvents} 
          background={$timelineStore.background}
          selectedEvent={$selectedEvent}
          on:select={(e) => timelineActions.selectEvent(e.detail.slug)}
        />
      </div>
      
      <!-- Tree View -->
      <div class="timeline-view pt-4 relative {$timelineStore.viewMode !== 'tree' ? 'hidden' : ''}">
        <TreeView 
          events={$filteredEvents} 
          background={$timelineStore.background}
          selectedEvent={$selectedEvent}
          on:select={(e) => timelineActions.selectEvent(e.detail.slug)}
        />
      </div>
      
      <!-- Map View -->
      <div class="timeline-view pt-4 relative {$timelineStore.viewMode !== 'map' ? 'hidden' : ''}">
        <MapView 
          events={$filteredEvents} 
          background={$timelineStore.background}
          selectedEvent={$selectedEvent}
          on:select={(e) => timelineActions.selectEvent(e.detail.slug)}
        />
      </div>
    </div>
    
    <!-- Top control bar - positioned absolutely with inline styles -->
    <div id="timelineTopControls" class="timeline-custom-controls absolute top-0 left-0 right-0 flex flex-row items-center justify-between p-2 z-[999]" 
         style="background-color: rgba(0,0,0,0.4); backdrop-filter: blur(4px); color: white;">
      <!-- Left side: Era filter (moved from bottom) -->
      <div class="flex items-center">
        <div class="era-dropdown-container">
<!--           <span class="text-xs mr-2" style="color: white;">Era:</span> -->
      <select on:change={handleEraFilter}
              class="bg-black/40 hover:bg-black/50 text-xs px-2 py-1 rounded-md border border-white/20 era-select"
              style="color: white; background-color: rgba(0,0,0,0.4); font-size: 0.75rem;"
              aria-label="Select era">
        <option value="all-eras">All Eras</option>
        <option value="all-time">All Time</option>
        {#each Object.entries(eraConfig).filter(([key]) => !['all-eras', 'all-time'].includes(key)) as [value, config]}
          <option value={value}
                  data-start-year={config.startYear}
                  data-end-year={config.endYear}>
            {config.displayName}
          </option>
        {/each}
      </select>
        </div>
      </div>
        
      <!-- Right side view switcher (keeping it in the top right) -->
      <div class="flex items-center ml-auto">
        <div class="timeline-view-switcher flex rounded-md overflow-hidden">
          <button 
            on:click={() => handleSetViewMode('timeline')}
            class="custom-btn px-2 py-1 flex items-center text-xs {$timelineStore.viewMode === 'timeline' ? 'bg-[var(--primary)]' : 'bg-black/30'} hover:bg-white/20 active:bg-white/30"
            style="color: white; display: flex; align-items: center; justify-content: center;"
          >
            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-4 h-4 mr-1" style="color: white;">
              <path stroke-linecap="round" stroke-linejoin="round" d="M3.75 6.75h16.5M3.75 12h16.5m-16.5 5.25H12" />
            </svg>
            Timeline
          </button>
          
          <button 
            on:click={() => handleSetViewMode('list')}
            class="custom-btn px-2 py-1 flex items-center text-xs {$timelineStore.viewMode === 'list' ? 'bg-[var(--primary)]' : 'bg-black/30'} hover:bg-white/20 active:bg-white/30"
            style="color: white; display: flex; align-items: center; justify-content: center;"
          >
            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-4 h-4 mr-1" style="color: white;">
              <path stroke-linecap="round" stroke-linejoin="round" d="M8.25 6.75h12M8.25 12h12m-12 5.25h12M3.75 6.75h.007v.008H3.75V6.75zm.375 0a.375.375 0 11-.75 0 .375.375 0 01.75 0zM3.75 12h.007v.008H3.75V12zm.375 0a.375.375 0 11-.75 0 .375.375 0 01.75 0zm-.375 5.25h.007v.008H3.75v-.008zm.375 0a.375.375 0 11-.75 0 .375.375 0 01.75 0z" />
            </svg>
            List
          </button>
          
          <button 
            on:click={() => handleSetViewMode('tree')}
            class="custom-btn px-2 py-1 flex items-center text-xs {$timelineStore.viewMode === 'tree' ? 'bg-[var(--primary)]' : 'bg-black/30'} hover:bg-white/20 active:bg-white/30"
            style="color: white; display: flex; align-items: center; justify-content: center;"
          >
            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-4 h-4 mr-1" style="color: white;">
              <path stroke-linecap="round" stroke-linejoin="round" d="M3.75 3v11.25A2.25 2.25 0 006 16.5h2.25M3.75 3h-1.5m1.5 0h16.5m0 0h1.5m-1.5 0v11.25A2.25 2.25 0 0118 16.5h-2.25m-7.5 0h7.5m-7.5 0l-1 3m8.5-3l1 3m0 0l.5 1.5m-.5-1.5h-9.5m0 0l-.5 1.5m.75-9l3-3 2.148 2.148A12.061 12.061 0 0116.5 7.605" />
            </svg>
            Tree
          </button>
          
          <button 
            on:click={() => handleSetViewMode('map')}
            class="custom-btn px-2 py-1 flex items-center text-xs {$timelineStore.viewMode === 'map' ? 'bg-[var(--primary)]' : 'bg-black/30'} hover:bg-white/20 active:bg-white/30"
            style="color: white; display: flex; align-items: center; justify-content: center;"
          >
            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-4 h-4 mr-1" style="color: white;">
              <path stroke-linecap="round" stroke-linejoin="round" d="M9 6.75V15m6-6v8.25m.503 3.498l4.875-2.437c.381-.19.622-.58.622-1.006V4.82c0-.836-.88-1.38-1.628-1.006l-3.869 1.934c-.317.159-.69.159-1.006 0L9.503 3.252a1.125 1.125 0 00-1.006 0L3.622 5.689C3.24 5.88 3 6.27 3 6.695V19.18c0 .836.88 1.38 1.628 1.006l3.869-1.934c-.317-.159-.69-.159 1.006 0l4.994 2.497c.317.158.69.158 1.006 0z" />
            </svg>
            Map
          </button>
        </div>
      </div>
    </div>
    
    <!-- Bottom control bar - positioned absolutely with inline styles -->
    <div id="timelineBottomControls" class="timeline-custom-controls absolute bottom-0 left-0 right-0 flex items-center justify-between p-2 z-[999]"
         style="background-color: rgba(0,0,0,0.4); backdrop-filter: blur(4px); color: white; height: 44px; overflow: hidden;">
      <!-- Left side: Reset view button (moved from right) -->
      <div class="flex items-center">
        <button on:click={handleResetView}
                class="custom-btn bg-white/20 px-3 py-1 rounded-md hover:bg-white/30 active:bg-white/40"
                style="color: white; display: flex; align-items: center; justify-content: center;"
                aria-label="Reset view">
          <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-4 h-4 mr-1" style="color: white;">
            <path stroke-linecap="round" stroke-linejoin="round" d="M15 15l6-6m0 0l-6-6m6 6H9a6 6 0 000 12h3" />
          </svg>
          <span class="text-xs" style="color: white;">Reset View</span>
        </button>
      </div>
      
      <!-- Right side: Zoom and Pan controls in a single horizontal row -->
      <div class="flex items-center ml-auto">
        <!-- All controls in a single horizontal row -->
        <div class="flex items-center">
          <!-- Pan left button -->
          <button on:click={() => handlePan(50, 0)}
            class="custom-btn w-8 h-8 rounded-md mr-1 hover:bg-white/20 active:bg-white/30"
            style="color: white; display: flex; align-items: center; justify-content: center;"
            aria-label="Pan left">
            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-5 h-5" style="color: white;">
              <path stroke-linecap="round" stroke-linejoin="round" d="M10.5 19.5L3 12m0 0l7.5-7.5M3 12h18" />
            </svg>
          </button>
          
          <!-- Pan up button -->
          <button on:click={() => handlePan(0, 30)}
            class="custom-btn w-8 h-8 rounded-md mr-1 hover:bg-white/20 active:bg-white/30"
            style="color: white; display: flex; align-items: center; justify-content: center;"
            aria-label="Pan up">
            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-5 h-5" style="color: white;">
              <path stroke-linecap="round" stroke-linejoin="round" d="M4.5 15.75l7.5-7.5 7.5 7.5" />
            </svg>
          </button>
          
          <!-- Pan down button -->
          <button on:click={() => handlePan(0, -30)}
            class="custom-btn w-8 h-8 rounded-md mr-1 hover:bg-white/20 active:bg-white/30"
            style="color: white; display: flex; align-items: center; justify-content: center;"
            aria-label="Pan down">
            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-5 h-5" style="color: white;">
              <path stroke-linecap="round" stroke-linejoin="round" d="M19.5 8.25l-7.5 7.5-7.5-7.5" />
            </svg>
          </button>
          
          <!-- Pan right button -->
          <button on:click={() => handlePan(-50, 0)}
            class="custom-btn w-8 h-8 rounded-md mr-1 hover:bg-white/20 active:bg-white/30"
            style="color: white; display: flex; align-items: center; justify-content: center;"
            aria-label="Pan right">
            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-5 h-5" style="color: white;">
              <path stroke-linecap="round" stroke-linejoin="round" d="M13.5 4.5L21 12m0 0l-7.5 7.5M21 12H3" />
            </svg>
          </button>
          
          <div class="h-5 border-r border-white/20 mx-2"></div>
          
          <!-- Zoom out button -->
          <button on:click={handleZoomOut}
            class="custom-btn w-8 h-8 rounded-md mr-1 hover:bg-white/20 active:bg-white/30"
            style="color: white; display: flex; align-items: center; justify-content: center;"
            aria-label="Zoom out">
            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-5 h-5" style="color: white;">
              <path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607zM13.5 10.5h-6" />
            </svg>
          </button>

          <!-- Zoom in button -->
          <button on:click={handleZoomIn}
            class="custom-btn w-8 h-8 rounded-md hover:bg-white/20 active:bg-white/30"
            style="color: white; display: flex; align-items: center; justify-content: center;"
            aria-label="Zoom in">
            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-5 h-5" style="color: white;">
              <path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607zM7.5 10.5h6m-3-3v6" />
            </svg>
          </button>
        </div>
      </div>
    </div>
    
    <!-- Mobile gesture hint -->
    {#if isMobile}
      <div class="timeline-gesture-hint {showGestureHint ? 'visible' : ''}" 
           aria-hidden="{!showGestureHint}">
        <div class="flex items-center">
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" class="w-5 h-5 mr-2 text-white">
            <path fill="currentColor" d="M9 11.24V7.5C9 6.12 10.12 5 11.5 5S14 6.12 14 7.5v3.74c1.21-.81 2-2.18 2-3.74C16 5.01 13.99 3 11.5 3S7 5.01 7 7.5c0 1.56.79 2.93 2 3.74zm5.08 2.26H13v-6c0-.83-.67-1.5-1.5-1.5S10 6.67 10 7.5v10.74l-4.04-.85-1.21 1.23L10.13 24h8.67l1.07-7.62-5.79-2.88z"/>
          </svg>
          <span>Pinch to zoom, drag to move</span>
        </div>
      </div>
    {/if}
  </div>
</div>

<style>
  /* Minimal core styles */
  .timeline-wrapper {
    position: relative;
  }
  
  .timeline-viewport {
    transform: translateZ(0);
    touch-action: none;
  }
  
  .timeline-banner-mode {
    margin-top: 0 !important;
    margin-bottom: 0 !important;
    padding-top: 0 !important;
    padding-bottom: 0 !important;
  }
  
  /* Make sure our custom controls are visible */
  .timeline-custom-controls {
    color: white !important;
  }
  
  /* Make dropdown open upwards instead of downwards */
  .era-dropdown-container {
    position: relative;
  }
  
  .era-select {
    appearance: menulist-button;
    position: relative;
    color: white !important;
    background-color: rgba(0,0,0,0.4) !important;
  }
  
  /* For webkit browsers */
  .era-select::-webkit-calendar-picker-indicator {
    filter: invert(1) opacity(0.7);
  }
  
  /* This creates the effect of the dropdown expanding upward */
  .era-dropdown-container:focus-within .era-select option {
    transform: translateY(-100%);
    transform-origin: bottom;
    background-color: #333 !important;
    color: white !important;
  }

  /* Mobile gesture hint styles */
  .timeline-gesture-hint {
    position: absolute;
    bottom: 60px;
    left: 50%;
    transform: translateX(-50%);
    background-color: rgba(0, 0, 0, 0.7);
    color: white;
    padding: 8px 16px;
    border-radius: 20px;
    font-size: 14px;
    transition: opacity 0.3s ease, transform 0.3s ease;
    opacity: 0;
    pointer-events: none;
    z-index: 1000;
  }

  .timeline-gesture-hint.visible {
    opacity: 1;
    animation: hintPulse 3s ease-in-out 1 forwards;
  }

  @keyframes hintPulse {
    0% { opacity: 0; transform: translateX(-50%) translateY(10px); }
    10% { opacity: 1; transform: translateX(-50%) translateY(0); }
    80% { opacity: 1; transform: translateX(-50%) translateY(0); }
    100% { opacity: 0; transform: translateX(-50%) translateY(-10px); }
  }
</style>