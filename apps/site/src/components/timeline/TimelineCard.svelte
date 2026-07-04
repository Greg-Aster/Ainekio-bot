<script lang="ts">
  import { fly, fade } from 'svelte/transition';
  import { cubicOut } from 'svelte/easing';
  import type { TimelineEvent } from '../../services/TimelineService.client';
  import { getEraDisplayName } from '../../services/TimelineService.client';
  
  // Props
  export let event: TimelineEvent;
  export let isSelected: boolean = false;
  export let compact: boolean = false;
  export let position: 'top' | 'bottom' | 'left' | 'right' = 'bottom';
  export let isMobile: boolean = false;
  
  // Helper function to get CSS classes for era badges
  function getEraBadgeClass(era?: string): string {
    if (!era) return "bg-[oklch(0.9_0.05_var(--hue))/0.1] dark:bg-[oklch(0.3_0.05_var(--hue))/0.2] text-[oklch(0.4_0.05_var(--hue))] dark:text-[oklch(0.9_0.05_var(--hue))]";
    
    // Match your existing era badge classes
    switch(era) {
      case 'pre-spork':
        return "bg-[oklch(0.8_0.1_var(--hue))/0.1] dark:bg-[oklch(0.8_0.1_var(--hue))/0.2] text-[oklch(0.3_0.1_var(--hue))] dark:text-[oklch(0.8_0.1_var(--hue))]";
      case 'spork-uprising':
        return "bg-[oklch(0.7_0.2_var(--hue))/0.1] dark:bg-[oklch(0.7_0.2_var(--hue))/0.2] text-[oklch(0.3_0.2_var(--hue))] dark:text-[oklch(0.7_0.2_var(--hue))]";
      case 'snuggaloid':
        return "bg-[oklch(0.6_0.3_var(--hue))/0.1] dark:bg-[oklch(0.6_0.3_var(--hue))/0.2] text-[oklch(0.3_0.3_var(--hue))] dark:text-[oklch(0.6_0.3_var(--hue))]";
      case 'post-extinction':
        return "bg-[oklch(0.5_0.1_var(--hue))/0.1] dark:bg-[oklch(0.5_0.1_var(--hue))/0.2] text-[oklch(0.2_0.1_var(--hue))] dark:text-[oklch(0.5_0.1_var(--hue))]";
      default:
        return "bg-[oklch(0.9_0.05_var(--hue))/0.1] dark:bg-[oklch(0.3_0.05_var(--hue))/0.2] text-[oklch(0.4_0.05_var(--hue))] dark:text-[oklch(0.9_0.05_var(--hue))]";
    }
  }
</script>

<div 
  class="timeline-card card-base {isMobile ? 'fixed-position mobile-card' : 'absolute z-30'} bg-[var(--card-bg)] backdrop-blur-sm shadow-lg
         {isMobile ? 'w-[280px] h-auto' : 'w-[200px]'} 
         {compact ? 'p-2 text-sm' : 'p-3'}
         {isSelected ? 'border-2 border-[var(--primary)]' : 'border border-transparent'}"
  class:timeline-card-top={position === 'top' && !isMobile}
  class:timeline-card-bottom={position === 'bottom' && !isMobile}
  class:timeline-card-left={position === 'left' && !isMobile}
  class:timeline-card-right={position === 'right' && !isMobile}
  in:fly="{{ y: isMobile ? 20 : position === 'top' ? 10 : position === 'bottom' ? -10 : 0, 
            x: isMobile ? 0 : position === 'left' ? 10 : position === 'right' ? -10 : 0, 
            duration: 1000,
            easing: cubicOut }}"
  out:fly="{{ y: isMobile ? 20 : position === 'top' ? 10 : position === 'bottom' ? -10 : 0, 
             x: isMobile ? 0 : position === 'left' ? 10 : position === 'right' ? -10 : 0, 
             duration: 200,
             easing: cubicOut }}"
>
  <!-- Card content -->
  <div class="font-bold text-75 text-sm mb-1 card-title">
    <!-- {event.year}: --> {event.title}
  </div>
  
  {#if !compact || isMobile}
    <div class="text-50 text-xs {isMobile ? 'line-clamp-3' : 'line-clamp-2'} card-description">
      {event.description}
    </div>
  {/if}
  
  <a href="/posts/{event.slug}/#post-container" class="timeline-link text-[0.65rem] mt-1 inline-block py-0.5 px-1.5 rounded-full bg-[oklch(0.9_0.05_var(--hue))/0.1] dark:bg-[oklch(0.3_0.05_var(--hue))/0.2] text-[oklch(0.4_0.05_var(--hue))] dark:text-[oklch(0.9_0.05_var(--hue))]">
    View Event →
  </a>
  
  <!-- Card arrow/pointer (added by CSS) - only show for non-mobile -->
  {#if !isMobile}
    <div class="card-pointer absolute bg-inherit"></div>
  {/if}
</div>

<style>
  /* These styles could be moved to timeline-styles.css */
  .timeline-card {
    box-shadow: 0 0 15px rgba(0, 0, 0, 0.1), 0 0 5px rgba(var(--primary-rgb, 0 0 0), 0.3);
    border-radius: var(--radius-large, 12px);
    /* Remove these two lines:
    opacity: 0;
    animation: fadeIn 0.3s forwards;
    */
  }

  /* And remove this keyframe definition: 
  @keyframes fadeIn {
    from { opacity: 0; }
    to { opacity: 1; }
  }
  */
  
  .timeline-era-badge {
    text-transform: capitalize;
    transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  }
  
  /* Card pointer styles */
  .card-pointer {
    width: 8px;
    height: 8px;
    transform: rotate(45deg);
    border: inherit;
  }
  
  /* Fixed position mobile card */
  .fixed-position {
    position: relative;
    bottom: auto;
    top: auto;
    left: auto;
    right: auto;
    transform: none !important;
  }

  /* Mobile card styling */
  .mobile-card {
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    height: auto;
    max-height: 160px;
    width: 280px;
    border-radius: 8px;
    box-shadow: 0 4px 15px rgba(0, 0, 0, 0.15);
  }
  
  .mobile-card .card-title {
    font-size: 0.9rem;
  }
  
  .mobile-card .card-description {
    flex: 1;
    margin-bottom: 8px;
    font-size: 0.75rem;
  }
  
  /* Positioning for different card locations */
  .timeline-card-top {
    bottom: 30px;
    transform: translateX(-50%);
  }
  
  .timeline-card-top .card-pointer {
    border-bottom-style: solid;
    border-right-style: solid;
    border-top-style: none;
    border-left-style: none;
    bottom: -4px;
    left: 50%;
    margin-left: -4px;
  }
  
  .timeline-card-bottom {
    top: 30px;
    transform: translateX(-50%);
  }
  
  .timeline-card-bottom .card-pointer {
    border-top-style: solid;
    border-left-style: solid;
    border-bottom-style: none;
    border-right-style: none;
    top: -4px;
    left: 50%;
    margin-left: -4px;
  }
  
  .timeline-card-left {
    right: 30px;
    transform: translateY(-50%);
  }
  
  .timeline-card-left .card-pointer {
    border-right-style: solid;
    border-top-style: solid;
    border-bottom-style: none;
    border-left-style: none;
    right: -4px;
    top: 50%;
    margin-top: -4px;
  }
  
  .timeline-card-right {
    left: 30px;
    transform: translateY(-50%);
  }
  
  .timeline-card-right .card-pointer {
    border-left-style: solid;
    border-bottom-style: solid;
    border-top-style: none;
    border-right-style: none;
    left: -4px;
    top: 50%;
    margin-top: -4px;
  }
  
  /* Hover effect */
  .timeline-link {
    text-transform: capitalize;
    transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  }
  
  .timeline-link:hover {
    background-color: var(--primary) !important;
    color: white !important;
    text-decoration: none;
  }
  
  :global(.timeline-card:hover .timeline-link) {
    background-color: var(--primary) !important;
    color: white !important;
  }
</style>