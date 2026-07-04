<script lang="ts">
  import { onMount } from 'svelte';
  import { createEventDispatcher } from 'svelte';
  import type { TimelineEvent } from '../../../services/TimelineService.client';
  import { getEraDisplayName, getEraClasses } from '../../../services/TimelineService.client';
  import TimelineCard from '../TimelineCard.svelte'; // Import the same card component used in TimelineCore
  
  // Props
  export let events: TimelineEvent[] = [];
  export let background: string = '/assets/banner/0001.png';
  export let selectedEvent: TimelineEvent | null = null;
  
  // Create Svelte event dispatcher
  const dispatch = createEventDispatcher();
  
  // Filter events that have locations
  $: eventsWithLocations = events.filter(event => event.location);
  
  // Reference to root element for DOM event handling
  let rootElement: HTMLElement;
  
  // Tracking hover/selection state
  let hoveredEventSlug: string | null = null;
  
  // Enhanced event handling with Svelte's dispatcher
  function handleSelect(event: TimelineEvent) {
    console.log(`MapView handling selection for: ${event.title} (${event.slug})`);
    
    // If this event is already selected, navigate to its page
    if (selectedEvent && selectedEvent.slug === event.slug) {
      console.log(`MapView navigating to: /posts/${event.slug}/`);
      window.location.href = `/posts/${event.slug}/`;
      return;
    }
    
    // Otherwise, dispatch selection event using Svelte's dispatcher
    console.log(`MapView dispatching select event for: ${event.slug}`);
    dispatch('select', { slug: event.slug });
  }
  
  // Handle hover for showing information cards
  function handleHover(event: TimelineEvent) {
    hoveredEventSlug = event.slug;
  }
  
  function clearHover() {
    hoveredEventSlug = null;
  }
  
  // Generate a pseudo-random x,y coordinate based on location name
  // This creates a consistent position for each location
  function getLocationCoordinates(location: string) {
    // Simple hash function for pseudo-random but consistent coordinates
    const hash = [...location].reduce((h, c) => (h * 31 + c.charCodeAt(0)) % 360, 0);
    
    // Position the pin in the map area
    const x = 50 + (hash % 300);
    const y = 50 + ((hash * 17) % 200);
    
    return { x, y };
  }
  
  // Initialize DOM events and logging
  onMount(() => {
    console.log("MapView mounted with locations:", eventsWithLocations.length);
    
    // Add debugging log to check if component is properly rendering
    console.log("MapView elements:", {
      rootElement,
      pins: document.querySelectorAll('.map-pin').length,
      cards: document.querySelectorAll('.location-card').length
    });
  });
</script>

<div class="map-view relative" bind:this={rootElement}>
  <!-- Main scrollable container - Added scrollbar-timeline class and overflow-y-auto -->
  <div class="relative z-10 overflow-y-auto scrollbar-timeline" style="max-height: calc(100vh - 160px);">
    <div class="px-4">
      <!-- Map visualization area -->
      <div class="map-container relative card-base bg-[oklch(0.95_0.03_var(--hue))/80] dark:bg-[oklch(0.2_0.03_var(--hue))/80] backdrop-blur-sm rounded-md overflow-hidden" 
           style="height: calc(70vh - 140px); min-height: 300px;">
        
        <!-- Background image with overlay -->
        <div class="absolute inset-0 -z-10 overflow-hidden">
          <img src={background} alt="Map background" class="w-full h-full object-cover opacity-20" />
          <div class="absolute inset-0 bg-gradient-to-r from-[oklch(0.35_0.05_var(--hue))] to-[oklch(0.25_0.05_var(--hue))] opacity-30 dark:opacity-10"></div>
        </div>
        
        <!-- Map grid with location pins -->
        <svg viewBox="0 0 400 300" xmlns="http://www.w3.org/2000/svg" class="w-full h-full relative z-10 pointer-events-none">
          <!-- Simple map grid background -->
          <defs>
            <pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse">
              <path d="M 40 0 L 0 0 0 40" fill="none" stroke="currentColor" stroke-width="0.8" class="text-[var(--primary)]" opacity="0.2" />
            </pattern>
          </defs>
          <rect width="100%" height="100%" fill="url(#grid)" class="text-[var(--primary)]" />
          
          <!-- Simplified "continents" -->
          <path d="M 80,50 C 100,40 150,30 200,50 C 250,70 280,90 300,70 C 320,50 350,60 350,80 C 350,100 320,120 300,150 C 280,180 250,190 200,180 C 150,170 120,190 100,170 C 80,150 60,130 80,100 C 100,70 80,50 80,50 Z" 
                fill="oklch(0.7 0.1 var(--hue))" fill-opacity="0.7" stroke="oklch(0.5 0.2 var(--hue))" stroke-width="1.5" />
          
          <path d="M 30,200 C 40,180 70,170 100,190 C 130,210 160,200 170,220 C 180,240 150,260 120,250 C 90,240 60,250 50,230 C 40,210 30,200 30,200 Z"
                fill="oklch(0.6 0.15 var(--hue))" fill-opacity="0.7" stroke="oklch(0.5 0.2 var(--hue))" stroke-width="1.5" />
        </svg>
        
        <!-- Place pins for events with locations (outside SVG for better event handling) -->
        <div class="absolute inset-0">
          {#each eventsWithLocations as event}
            {@const coords = getLocationCoordinates(event.location || '')}
            
            <!-- Pin container with absolute positioning -->
            <div 
              class="map-pin absolute cursor-pointer pointer-events-auto"
              style="left: {coords.x / 4}%; top: {coords.y / 3}%; transform: translate(-50%, -50%);"
              on:mouseenter={() => handleHover(event)}
              on:mouseleave={clearHover}
              on:click={() => handleSelect(event)}
              on:dblclick={() => window.location.href = `/posts/${event.slug}/`}
              data-slug={event.slug}
            >
              <!-- Pin visualization -->
              <div 
                class="pin-circle transition-all duration-300 w-6 h-6 rounded-full flex items-center justify-center
                       {selectedEvent?.slug === event.slug || hoveredEventSlug === event.slug ? 'scale-150 shadow-glow' : ''}"
                style="background-color: {event.isKeyEvent 
                  ? 'oklch(0.8 0.2 var(--hue))' 
                  : 'oklch(0.6 0.1 var(--hue))'}"
              >
                <div class="w-4 h-4 rounded-full border-2 border-white/70"></div>
              </div>
              
              <!-- Year label -->
              <div class="absolute -bottom-6 left-1/2 transform -translate-x-1/2 text-xs font-bold text-white 
                          bg-[oklch(0.3_0.05_var(--hue))/70] px-1 rounded">
                {event.year}
              </div>
              
              <!-- Information card (shown on hover or selection) -->
              {#if (hoveredEventSlug === event.slug || selectedEvent?.slug === event.slug)}
                <div class="absolute z-20" style="top: {coords.y < 150 ? '120%' : '-200%'}; left: 0;">
                  <div class="relative w-48">
                    <TimelineCard 
                      event={event}
                      isSelected={selectedEvent?.slug === event.slug}
                      compact={false}
                      position={coords.y < 150 ? 'bottom' : 'top'}
                    />
                  </div>
                </div>
              {/if}
            </div>
          {/each}
        </div>
        
        <!-- Map legend overlay -->
        <div class="absolute top-4 right-4 bg-[oklch(0.9_0.03_var(--hue))/90] dark:bg-[oklch(0.2_0.05_var(--hue))/90] p-3 rounded-md text-sm text-75 backdrop-blur-sm shadow-md">
          <div class="font-bold mb-2">Map Legend</div>
          <div class="flex items-center mb-2">
            <div class="w-4 h-4 rounded-full bg-[oklch(0.6_0.1_var(--hue))] mr-2"></div>
            <span>Regular Event</span>
          </div>
          <div class="flex items-center">
            <div class="w-5 h-5 rounded-full bg-[oklch(0.8_0.2_var(--hue))] mr-1"></div>
            <span>Key Event</span>
          </div>
        </div>
        
        <!-- Empty state message if no locations -->
        {#if eventsWithLocations.length === 0}
          <div class="absolute inset-0 flex items-center justify-center">
            <div class="text-center p-8 bg-[oklch(0.95_0.03_var(--hue))/80] dark:bg-[oklch(0.2_0.03_var(--hue))/80] backdrop-blur-sm rounded-xl shadow-lg">
              <svg xmlns="http://www.w3.org/2000/svg" class="h-16 w-16 text-[var(--primary)] mx-auto mb-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 20l-5.447-2.724A1 1 0 013 16.382V5.618a1 1 0 011.447-.894L9 7m0 13l6-3m-6 3V7m6 10l4.553 2.276A1 1 0 0021 18.382V7.618a1 1 0 00-.553-.894L15 4m0 13V4m0 0L9 7" />
              </svg>
              <p class="text-75 font-bold text-lg">No Location Data Available</p>
              <p class="text-50 mt-2">Add timelineLocation to your posts to place events on this map.</p>
            </div>
          </div>
        {/if}
      </div>
      
      <!-- Timeline events that have locations listed below the map -->
      <div class="timeline-map-events mt-4">
        <h3 class="font-bold text-75 mb-2">Timeline Locations</h3>
        <div class="grid grid-cols-1 md:grid-cols-2 gap-2">
          {#each eventsWithLocations as event}
            <button 
              class="location-card flex items-center p-2 hover:bg-[var(--btn-card-bg-hover)] rounded-md transition-colors text-left {selectedEvent?.slug === event.slug ? 'bg-[oklch(0.95_0.025_var(--hue))/50] dark:bg-[oklch(0.25_0.025_var(--hue))/50]' : ''}"
              data-slug={event.slug}
              data-era={event.era}
              on:click={() => handleSelect(event)}
              on:dblclick={() => window.location.href = `/posts/${event.slug}/`}
              on:mouseenter={() => handleHover(event)}
              on:mouseleave={clearHover}
            >
              <div class="location-icon mr-2 text-[var(--primary)]">
                <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.244-4.243a8 8 0 1111.314 0z" />
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 11a3 3 0 11-6 0 3 3 0 016 0z" />
                </svg>
              </div>
              <div class="location-info">
                <div class="font-bold text-75 text-sm">{event.title} ({event.year})</div>
                <div class="text-50 text-xs">{event.location}</div>
              </div>
            </button>
          {/each}
        </div>
      </div>
      
      <!-- Extra padding to prevent content being cut off by footer/navbar - INCREASED -->
      <div class="h-40"></div>
    </div>
  </div>
</div>

<style lang="postcss">
  /* Map pin animations and highlights */
  .map-pin {
    transition: transform 0.3s ease-out;
    z-index: 5;
  }
  
  .map-pin:hover {
    z-index: 10;
  }
  
  /* Add glow effect for selected or hovered pins */
  .shadow-glow {
    box-shadow: 0 0 10px 2px oklch(0.65 0.3 var(--hue));
  }
  
  /* Location card hover effects */
  .location-card {
    transition: all 0.3s ease;
    border: 1px solid transparent;
  }
  
  .location-card:hover {
    border: 1px solid oklch(0.65 0.15 var(--hue));
    transform: translateX(5px);
  }
  
  /* Animation for map pins - pulsing effect */
  @keyframes pinPulse {
    0% { transform: scale(1); }
    50% { transform: scale(1.1); }
    100% { transform: scale(1); }
  }
  
  .pin-circle {
    animation: pinPulse 3s infinite;
  }
  
  /* Vary animation timing for more natural effect */
  .map-pin:nth-child(3n) .pin-circle {
    animation-duration: 4s;
  }
  
  .map-pin:nth-child(3n+1) .pin-circle {
    animation-duration: 5s;
  }
  
  .map-pin:nth-child(7n+2) .pin-circle {
    animation-duration: 3.5s;
  }
  
  /* Scrollbar styling to match your site - Added missing scrollbar styles */
  .scrollbar-timeline {
    scrollbar-width: thin;
    scrollbar-color: oklch(0.65 0.15 var(--hue)) transparent;
    padding-bottom: 2rem;
    scroll-behavior: smooth;
  }
  
  .scrollbar-timeline::-webkit-scrollbar {
    width: 8px;
  }
  
  .scrollbar-timeline::-webkit-scrollbar-track {
    background: transparent;
  }
  
  .scrollbar-timeline::-webkit-scrollbar-thumb {
    background-color: oklch(0.65 0.15 var(--hue));
    opacity: 0.5;
    border-radius: 20px;
    border: 2px solid transparent;
  }
</style>