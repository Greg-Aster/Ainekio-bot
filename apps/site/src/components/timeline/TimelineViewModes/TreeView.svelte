<script lang="ts">
  import { onMount } from 'svelte';
  import type { TimelineEvent } from '../../../services/TimelineService.client';
  import { getEraDisplayName, getEraClasses } from '../../../services/TimelineService.client';
  
  // Props
  export let events: TimelineEvent[] = [];
  export let background: string = '/assets/banner/0001.png';
  export let selectedEvent: TimelineEvent | null = null;
  
  // Reference to component root
  let rootElement: HTMLElement;
  
  import { createEventDispatcher } from 'svelte';
  const dispatch = createEventDispatcher();
  
  // Event handling with Svelte's dispatch
  function dispatchSelect(event: TimelineEvent) {
    // If this event is already selected, navigate to its page
    if (selectedEvent && selectedEvent.slug === event.slug) {
      console.log(`TreeView navigating to: /posts/${event.slug}/`);
      window.location.href = `/posts/${event.slug}/`;
      return;
    }
    
    // Otherwise, dispatch selection event using Svelte's dispatcher
    console.log(`TreeView selecting event: ${event.title} (${event.slug})`);
    dispatch('select', { slug: event.slug });
  }
  
  // Sort events by year
  $: sortedEvents = [...events].sort((a, b) => a.year - b.year);
  
  // Animation state
  let ready = false;
  
  onMount(() => {
    console.log("TreeView mounted, found events:", events.length);
    // Set ready state after a short delay
    setTimeout(() => {
      ready = true;
      console.log("TreeView ready state set to true");
    }, 100);
  });
  
</script>

<div class="tree-view relative" class:ready={ready} bind:this={rootElement}>
  <!-- Background image with overlay -->
  <div class="absolute inset-0 -z-10 overflow-hidden">
    <img src={background} alt="Timeline background" class="w-full h-full object-cover opacity-25" />
    <div class="absolute inset-0 bg-gradient-to-r from-[oklch(0.35_0.05_var(--hue))] to-[oklch(0.25_0.05_var(--hue))] opacity-40 dark:opacity-30"></div>
  </div>
  
  <!-- Scrollable container -->
  <div class="relative z-10 overflow-y-auto scrollbar-timeline" style="max-height: calc(100vh - 160px);">
    <div class="px-4">
      <div class="timeline-tree pl-8 relative">
        <!-- Main vertical line -->
        <div class="absolute left-4 top-0 bottom-0 w-0.5 bg-[var(--primary)] opacity-30"></div>
        
        {#each sortedEvents as event, i}
          <button 
            on:click={() => dispatchSelect(event)}
            on:dblclick={() => {
              console.log(`Double-click navigation to: /posts/${event.slug}/`);
              window.location.href = `/posts/${event.slug}/`;
            }}
            class="timeline-tree-node flex relative hover:bg-[var(--btn-card-bg-hover)] rounded-md p-2 mb-4 transition-colors text-left w-full {selectedEvent?.slug === event.slug ? 'bg-[oklch(0.95_0.025_var(--hue))/50] dark:bg-[oklch(0.25_0.025_var(--hue))/50]' : ''}"
            data-era={event.era}
            data-slug={event.slug}
            style="transition-delay: {i * 50}ms;"
          >
            <!-- Circle on the line -->
            <div class="absolute left-4 top-1/2 transform -translate-x-1/2 -translate-y-1/2">
              <div class="tree-node-circle {event.isKeyEvent ? 'w-5 h-5 bg-[var(--primary)]' : 'w-4 h-4 border-2 border-[var(--primary)] bg-[var(--card-bg)]'} rounded-full"></div>
            </div>
            
            <!-- Horizontal connector -->
            <div class="h-0.5 w-8 bg-[var(--primary)] opacity-30 absolute left-4 top-1/2 transform"></div>
            
            <!-- Event content -->
            <div class="pl-8 pt-2 pb-2">
              <div class="flex items-center mb-1">
                <span class="text-[var(--primary)] font-bold mr-2">{event.year}</span>
                <span class="text-xs py-0.5 px-2 rounded-full {getEraClasses(event.era || 'unknown')}" data-era={event.era}>
                  {getEraDisplayName(event.era || 'unknown')}
                </span>
                {#if event.isKeyEvent}
                  <span class="ml-2 text-xs font-bold py-0.5 px-2 rounded-full bg-[var(--primary)] text-white">Key Event</span>
                {/if}
              </div>
              <div class="event-title font-bold text-75 mb-1">{event.title}</div>
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
        
        <!-- Empty state if no events -->
        {#if sortedEvents.length === 0}
          <div class="flex flex-col items-center justify-center py-10 text-center card-base p-8 mt-10">
            <svg xmlns="http://www.w3.org/2000/svg" class="h-16 w-16 text-[var(--primary)]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            </svg>
            <div class="text-75 font-bold mt-4">No timeline events found</div>
            <div class="text-50 text-sm mt-2">
              Add timelineYear to your posts to see them in this timeline
            </div>
          </div>
        {/if}
      </div>
      
      <!-- Extra padding to prevent content being cut off by footer/navbar - INCREASED -->
      <div class="h-40"></div>
    </div>
  </div>
</div>

<style lang="postcss">
  /* Tree node animations - simplified approach */
  .timeline-tree-node {
    transition: all 0.5s ease;
    opacity: 0;
    transform: translateX(-20px);
  }
  
  .tree-view.ready .timeline-tree-node {
    opacity: 1;
    transform: translateX(0);
  }
  
  .timeline-tree-node:hover .tree-node-circle {
    transform: scale(1.2);
    box-shadow: 0 0 10px oklch(0.65 0.15 var(--hue));
  }
  
  .tree-node-circle {
    transition: all 0.3s ease-in-out;
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