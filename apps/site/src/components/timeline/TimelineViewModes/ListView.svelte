<script lang="ts">
  import { onMount } from 'svelte';
  import { groupEventsByEra } from '../../../services/TimelineService.client';
  import { getEraDisplayName, getEraClasses } from '../../../services/TimelineService.client';
  import type { TimelineEvent } from '../../../services/TimelineService.client';
  
  // Props
  export let events: TimelineEvent[] = [];
  export let background: string = '/assets/banner/0001.png';
  export let selectedEvent: TimelineEvent | null = null;
  
  // Group events by era
  $: eventsByEra = groupEventsByEra(events);
  
  // Reference to root element for DOM event handling
  let rootElement: HTMLElement;
  
  import { createEventDispatcher } from 'svelte';
  const dispatch = createEventDispatcher();
  
  // Enhanced event handling using Svelte's dispatch
  function handleSelect(event: TimelineEvent) {
    // If this event is already selected, navigate to its page
    if (selectedEvent && selectedEvent.slug === event.slug) {
      console.log(`ListView navigating to: /posts/${event.slug}/`);
      window.location.href = `/posts/${event.slug}/`;
      return;
    }
    
    // Otherwise, dispatch selection event using Svelte's dispatcher
    console.log(`ListView selecting event: ${event.title} (${event.slug})`);
    dispatch('select', { slug: event.slug });
  }
  
  // Initialize DOM events and logging
  onMount(() => {
    console.log("ListView mounted with events:", events.length);
    
    // Add global document listener to catch all select events for debugging
    const handleGlobalSelectEvent = (e: Event) => {
      const selectEvent = e as CustomEvent;
      if (selectEvent.type === 'select' && selectEvent.detail?.slug) {
        console.log('Global select event intercepted:', selectEvent.detail);
      }
    };
    
    document.addEventListener('select', handleGlobalSelectEvent);
    
    return () => {
      document.removeEventListener('select', handleGlobalSelectEvent);
    };
  });
</script>

<div class="list-view relative" bind:this={rootElement}>
  <!-- Background image with overlay -->
  <div class="absolute inset-0 -z-10 overflow-hidden">
    <img src={background} alt="Timeline background" class="w-full h-full object-cover opacity-25" />
    <div class="absolute inset-0 bg-gradient-to-r from-[oklch(0.35_0.05_var(--hue))] to-[oklch(0.25_0.05_var(--hue))] opacity-40 dark:opacity-30"></div>
  </div>
  
  <!-- Scrollable container -->
  <div class="relative z-10 overflow-y-auto scrollbar-timeline" style="max-height: calc(100vh - 160px);">
    <div class="px-4">
      {#each Object.entries(eventsByEra) as [era, eraEvents]}
        <div class="timeline-era mb-6">
          <div class="era-header px-3 py-2 rounded-md mb-2 font-bold {getEraClasses(era)}">
            {getEraDisplayName(era)} ({eraEvents[0].year} - {eraEvents[eraEvents.length - 1].year})
          </div>
          
          <div class="era-events">
            {#each eraEvents as event}
              <button 
                class="timeline-event-card flex hover:bg-[var(--btn-card-bg-hover)] rounded-md p-2 mb-2 transition-colors text-left w-full {selectedEvent?.slug === event.slug ? 'bg-[oklch(0.95_0.025_var(--hue))/50] dark:bg-[oklch(0.25_0.025_var(--hue))/50]' : ''}"
                data-era={event.era}
                data-slug={event.slug}
                on:click={() => handleSelect(event)}
                on:dblclick={() => {
                  console.log(`Double-click navigation to: /posts/${event.slug}/`);
                  window.location.href = `/posts/${event.slug}/`;
                }}
              >
                <div class="event-year w-16 font-bold text-center text-[var(--primary)]">
                  {event.year}
                </div>
                <div class="event-connector w-8 flex items-center justify-center relative">
                  <div class="h-full w-0.5 bg-[var(--primary)] opacity-30"></div>
                  <div class="w-3 h-3 rounded-full absolute {event.isKeyEvent ? 'bg-[var(--primary)]' : 'border-2 border-[var(--primary)] bg-[var(--card-bg)]'}"></div>
                </div>
                <div class="event-content flex-1">
                  <div class="event-title font-bold text-75">{event.title}</div>
                  <div class="event-description text-50 text-sm">{event.description}</div>
                  {#if event.location}
                    <div class="event-location text-xs mt-1 text-[var(--primary)]">
                      <svg xmlns="http://www.w3.org/2000/svg" class="inline-block h-3 w-3 mr-1" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"></path>
                        <circle cx="12" cy="10" r="3"></circle>
                      </svg>
                      {event.location}
                    </div>
                  {/if}
                </div>
              </button>
            {/each}
          </div>
        </div>
      {/each}
      
      <!-- Empty state if no events -->
      {#if Object.keys(eventsByEra).length === 0}
        <div class="flex flex-col items-center justify-center py-10 text-center card-base p-8">
          <svg xmlns="http://www.w3.org/2000/svg" class="h-16 w-16 text-[var(--primary)]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
          </svg>
          <div class="text-75 font-bold mt-4">No timeline events found</div>
          <div class="text-50 text-sm mt-2">
            Add timelineYear to your posts to see them in this timeline
          </div>
        </div>
      {/if}
      
      <!-- Extra padding to prevent content being cut off by footer/navbar - INCREASED -->
      <div class="h-40"></div>
    </div>
  </div>
</div>

<style lang="postcss">
  /* Add animation effects for era headers */
  .era-header {
    position: relative;
    overflow: hidden;
  }
  
  .era-header::after {
    content: '';
    position: absolute;
    top: 0;
    right: 0;
    width: 5px;
    height: 100%;
    background: linear-gradient(to right, transparent, oklch(0.65 0.15 var(--hue)), transparent);
    animation: shine 3s infinite linear;
    opacity: 0.5;
  }
  
  @keyframes shine {
    0% { transform: translateX(-100%); }
    100% { transform: translateX(1000%); }
  }
  
  /* Scrollbar styling to match your site */
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