<script lang="ts">
  import { onMount } from 'svelte';
  
  // Props
  export let era: string | undefined = undefined;
  export let isKeyEvent: boolean = false;
  export let isSelected: boolean = false;
  export let isHovered: boolean = false;
  export let size: number = 8;
  export let identifier: string = Math.random().toString(36).substring(2, 10);
  export let useEraColors: boolean = false;

  
// Era color mapping 
const eraColorMap = {
  'ancient-epoch': '#3b82f6',        // Blue
  'awakening-era': '#8b5cf6',        // Purple
  'golden-age': '#f59e0b',           // Orange
  'conflict-epoch': '#ec4899',       // Pink
  'singularity-conflict': '#ef4444', // Red
  'transcendent-age': '#14b8a6',     // Teal
  'final-epoch': '#22c55e',          // Green
  'unknown': '#6366f1'               // Indigo
};
  
  // Full color spectrum with direct color values
  const colorSpectrum = [
    // Reds
    '#ef4444', '#f43f5e',
    // Oranges
    '#f97316', '#f59e0b',
    // Yellows
    '#eab308', '#facc15',
    // Greens
    '#22c55e', '#10b981', '#14b8a6',
    // Blues
    '#06b6d4', '#0ea5e9', '#3b82f6', '#6366f1',
    // Purples
    '#8b5cf6', '#a855f7', '#d946ef',
    // Pinks
    '#ec4899', '#f43f5e'
  ];
  
  // Star types
  const starTypes = [
    'point',     // Simple point of light
    'classic',   // Classic star shape
    'sparkle',   // Star with sparkle effect
    'refraction', // Improved refraction star
    'halo',      // Star with halo
    'subtle'     // Subtle star with minimal decoration
  ];
  
  // Helper to get deterministic random values
  function hashCode(str): number {
    if (!str) return 0;
    let hash = 0;
    for (let i = 0; i < str.length; i++) {
      hash = ((hash << 5) - hash) + str.charCodeAt(i);
      hash |= 0;
    }
    return Math.abs(hash);
  }
  
  // Get a color from the color spectrum (without using era colors)
    function getStarColor(id: string): string {
    // If useEraColors is true and we have a valid era, use the era color
    if (useEraColors && era && eraColorMap[era]) {
      return eraColorMap[era];
    }
    
    // Otherwise use the original random color based on id
    const hash = hashCode(id);
    return colorSpectrum[hash % colorSpectrum.length];
  }
  
  // Get a secondary color that's the same as primary but with different opacity
  // (instead of a complementary color from the opposite side)
  function getSecondaryColor(primaryColor: string): string {
    // Just use the same color - we'll adjust opacity in the styling
    return primaryColor;
  }
  
  // Get star type
  function getStarType(id: string): string {
    const hash = hashCode(id);
    if (isKeyEvent) {
      // Key events get more elaborate stars
      return ['classic', 'sparkle', 'refraction', 'halo'][hash % 4];
    }
    return starTypes[hash % starTypes.length];
  }
  
  // Get a size factor for the star
  function getSizeFactor(): number {
    return isKeyEvent ? 1.2 : 0.85 + (Math.random() * 0.3);
  }
  
  // Get animation duration
  function getAnimationDuration(id: string): number {
    const hash = hashCode(id);
    return 4 + (hash % 5); // 4-8 second duration
  }
  
  // Create unique ID - no longer use era, use the identifier instead
  $: uniqueId = `star-${identifier}-${isKeyEvent ? 'key' : 'normal'}`;
  
  // Set reactive variables
  $: starType = getStarType(uniqueId);
  $: sizeFactor = getSizeFactor();
  $: finalSize = size * sizeFactor;
  $: mainColor = getStarColor(uniqueId);
  $: secondaryColor = getSecondaryColor(mainColor);
  $: animationDuration = getAnimationDuration(uniqueId);
  
  // For sparkle effect
  let showSparkle = false;
  let isInitialized = false;
  let showInitAnimation = false;
  
  onMount(() => {
    isInitialized = true;
    showInitAnimation = true;
    
    // Remove initialization effect after it finishes
    setTimeout(() => {
      showInitAnimation = false;
    }, 3000); // Match this to the animation duration
    
    return () => {
      // Nothing to clean up
    };
  });
</script>

<div 
  class="star-wrapper"
  class:is-selected={isSelected}
  class:is-hovered={isHovered}
  class:is-key-event={isKeyEvent}
  class:is-initialized={isInitialized}
  data-star-type={starType}
  style="
    --animation-duration: {animationDuration}s; 
    --star-size: {finalSize}px;
    --star-color: {mainColor};
    --secondary-color: {mainColor};
  "
>
  <!-- Glow effect -->
  <div class="star-glow"></div>
  
  <!-- Star shape based on type -->
  <svg xmlns="http://www.w3.org/2000/svg" 
       viewBox="0 0 24 24" 
       width={finalSize * 2}
       height={finalSize * 2}
       class="star-shape">
    
    {#if starType === 'point'}
      <!-- Simple point of light - no outer circle -->
      <circle cx="12" cy="12" r="1.8" fill={mainColor} />
    {:else if starType === 'classic'}
      <!-- Classic star shape -->
      <path d="M12 5l1.5 3.5 3.5 0.5-2.5 2.5 0.5 3.5-3-1.5-3 1.5 0.5-3.5-2.5-2.5 3.5-0.5z" 
            fill={mainColor} />
    {:else if starType === 'sparkle'}
      <!-- Sparkle star with multiple points -->
      <path d="M12 5l0.7 3 2.8 0.5-2 2 0.5 3-2-1.5-2 1.5 0.5-3-2-2 2.8-0.5z" 
            fill={mainColor} />
      <path d="M12 3v18M3 12h18" 
            stroke={mainColor} 
            stroke-width="0.4" 
            opacity="0.4" />
    {:else if starType === 'refraction'}
      <!-- Improved refraction star - smaller center -->
      <circle cx="12" cy="12" r="1.5" fill={mainColor} />
      <!-- Horizontal and vertical lines -->
      <path d="M12 6v12M6 12h12" 
            stroke={mainColor} 
            stroke-width="0.7" 
            opacity="0.6" 
            class="refraction-lines" />
      <!-- Diagonal lines - very subtle -->
      <path d="M8 8l8 8M8 16l8-8" 
            stroke={mainColor} 
            stroke-width="0.3" 
            opacity="0.3" 
            class="refraction-lines" />
    {:else if starType === 'halo'}
      <!-- Star with halo - smaller circles -->
      <circle cx="12" cy="12" r="1.5" fill={mainColor} />
      <circle cx="12" cy="12" r="2.5" fill={mainColor} opacity="0.4" />
      <circle cx="12" cy="12" r="3.5" fill={mainColor} opacity="0.15" />
    {:else}
      <!-- Subtle star - no outer circle -->
      <circle cx="12" cy="12" r="1.2" fill={mainColor} />
      <path d="M10 9l4 6M9 12l6 0" 
            stroke={mainColor} 
            stroke-width="0.4" 
            opacity="0.5" />
    {/if}
    
    <!-- Inner glow for key events - same color -->
    {#if isKeyEvent}
      <circle cx="12" cy="12" r="2" 
              fill={mainColor} 
              opacity="0.5" 
              class="inner-glow" />
    {/if}
  </svg>

  <!-- Add orbital effects to all stars, with enhanced version for selected ones -->
  <div class="orbital-effect">
    <!-- Base orbital rings (visible on all stars) -->
    <div class="orbital-ring orbital-base orbital-ring-1"></div>
    
    <!-- Enhanced orbitals for selected events -->
    {#if isSelected}
      <div class="orbital-ring orbital-selected orbital-ring-1"></div>
      <div class="orbital-ring orbital-selected orbital-ring-2"></div>
    {/if}
    
    <!-- Initialization orbital effect -->
    {#if showInitAnimation}
      <div class="orbital-ring orbital-init"></div>
    {/if}
  </div>
</div>

<style>
  /* Base star styles */
  .star-wrapper {
    position: relative;
    display: flex;
    align-items: center;
    justify-content: center;
    filter: drop-shadow(0 0 5px var(--star-color));
    transition: transform 0.3s ease, filter 0.3s ease;
  }
  
  /* Glow effect - customized by star type */
  .star-glow {
    position: absolute;
    top: 50%;
    left: 50%;
    width: calc(var(--star-size) * 2);
    height: calc(var(--star-size) * 2);
    border-radius: 50%;
    transform: translate(-50%, -50%);
    background: radial-gradient(
      circle,
      var(--star-color) 0%,
      rgba(255,255,255,0) 70%
    );
    opacity: 0.5; /* Reduced opacity */
    animation: glowPulse var(--animation-duration, 4s) infinite alternate ease-in-out;
    pointer-events: none;
  }
  
  /* Star shape */
  .star-shape {
    position: relative;
    z-index: 2;
    filter: drop-shadow(0 0 1px var(--star-color));
  }
  
  /* Inner glow animation */
  .inner-glow {
    animation: innerGlowPulse var(--animation-duration, 3s) infinite alternate ease-in-out;
  }
  
  /* Selected state */
  .is-selected {
    filter: 
      drop-shadow(0 0 10px var(--star-color))
      drop-shadow(0 0 4px var(--star-color)) !important;
    z-index: 10;
    transform: scale(1.15);
  }
  
  .is-selected .star-glow {
    opacity: 0.8;
    width: calc(var(--star-size) * 2);
    height: calc(var(--star-size) * 2);
  }
  
  /* Hovered state */
  .is-hovered {
    filter: drop-shadow(0 0 8px var(--star-color));
    z-index: 5;
  }
  
  /* Key event state */
  .is-key-event {
    filter: 
      drop-shadow(0 0 7px var(--star-color))
      drop-shadow(0 0 3px var(--star-color));
  }
  
  /* Orbital effect for all stars */
  .orbital-effect {
    position: absolute;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    pointer-events: none;
    z-index: 5;
  }

  .orbital-ring {
    position: absolute;
    top: 50%;
    left: 50%;
    border-radius: 50%;
    border: 1px solid var(--star-color);
    transform: translate(-50%, -50%);
    opacity: 0;
  }

  /* Base orbital for all stars - smaller and slower */
  .orbital-base {
    width: calc(var(--star-size) * 1.5); /* Half the size */
    height: calc(var(--star-size) * 1.5);
    animation: orbital-pulse-base 8s infinite ease-in-out; /* Half the speed (8s vs 4s) */
    opacity: 0;
    border-color: var(--star-color);
  }

  /* Enhanced orbitals only for selected stars - larger and faster */
  .orbital-selected.orbital-ring-1 {
    width: calc(var(--star-size) * 5);
    height: calc(var(--star-size) * 5);
    animation: orbital-pulse 4s infinite ease-in-out;
  }

  .orbital-selected.orbital-ring-2 {
    width: calc(var(--star-size) * 4.5);
    height: calc(var(--star-size) * 4.5);
    animation: orbital-pulse 4s infinite ease-in-out;
    animation-delay: 2s; /* Offset for second ring */
  }
  
  /* Initialization orbital effect */
  .orbital-init {
    width: calc(var(--star-size) * 5);
    height: calc(var(--star-size) * 5);
    animation: orbital-init 3s ease-out forwards;
    border-color: var(--star-color);
    border-width: 2px;
  }

  /* Animation for base (non-selected) orbital - slower and more subtle */
  @keyframes orbital-pulse-base {
    0% {
      transform: translate(-50%, -50%) scale(0.9) rotate(0deg);
      opacity: 0;
    }
    20% {
      transform: translate(-50%, -50%) scale(1) rotate(22.5deg);
      opacity: 0.2; /* More subtle opacity */
    }
    60% {
      transform: translate(-50%, -50%) scale(1.1) rotate(67.5deg);
      opacity: 0.1;
    }
    100% {
      transform: translate(-50%, -50%) scale(1.2) rotate(90deg);
      opacity: 0;
    }
  }

  /* Animation for selected orbital - faster and more prominent */
  @keyframes orbital-pulse {
    0% {
      transform: translate(-50%, -50%) scale(0.9) rotate(0deg);
      opacity: 0;
      border-width: 1px;
    }
    20% {
      transform: translate(-50%, -50%) scale(1) rotate(45deg);
      opacity: 0.8;
      border-width: 1.5px;
    }
    60% {
      transform: translate(-50%, -50%) scale(1.2) rotate(135deg);
      opacity: 0.4;
      border-width: 1px;
    }
    100% {
      transform: translate(-50%, -50%) scale(1.5) rotate(180deg);
      opacity: 0;
      border-width: 0.5px;
    }
  }
  
  /* Animation for initialization effect */
  @keyframes orbital-init {
    0% {
      transform: translate(-50%, -50%) scale(0.2);
      opacity: 0.9;
    }
    50% {
      transform: translate(-50%, -50%) scale(1.5);
      opacity: 0.7;
    }
    100% {
      transform: translate(-50%, -50%) scale(3);
      opacity: 0;
    }
  }
  
  /* Refraction animation */
  .refraction-lines {
    animation: refractionTwinkle var(--animation-duration, 4s) infinite alternate ease-in-out;
  }
  
  /* Custom glow styles for different star types */
  .star-wrapper[data-star-type="refraction"] .star-glow {
    background: radial-gradient(
      circle,
      var(--star-color) 0%,
      rgba(255,255,255,0) 80%
    ), 
    linear-gradient(
      to right,
      rgba(255,255,255,0) 35%,
      var(--star-color) 50%,
      rgba(255,255,255,0) 65%
    ),
    linear-gradient(
      to bottom,
      rgba(255,255,255,0) 35%,
      var(--star-color) 50%,
      rgba(255,255,255,0) 65%
    );
    opacity: 0.4;
    width: calc(var(--star-size) * 5);
    height: calc(var(--star-size) * 5);
  }

  .star-wrapper[data-star-type="halo"] .star-glow {
    background: radial-gradient(
      circle,
      var(--star-color) 0%,
      var(--star-color) 10%,
      rgba(255,255,255,0) 70%
    );
    opacity: 0.5;
    width: calc(var(--star-size) * 4);
    height: calc(var(--star-size) * 4);
    animation: haloBreathing var(--animation-duration, 6s) infinite alternate ease-in-out;
  }

  .star-wrapper[data-star-type="sparkle"] .star-glow {
    background: 
      radial-gradient(
        circle,
        var(--star-color) 0%,
        rgba(255,255,255,0) 60%
      ),
      linear-gradient(
        to right,
        rgba(255,255,255,0) 45%,
        var(--star-color) 50%,
        rgba(255,255,255,0) 55%
      ),
      linear-gradient(
        to bottom,
        rgba(255,255,255,0) 45%,
        var(--star-color) 50%,
        rgba(255,255,255,0) 55%
      );
    opacity: 0.4;
    width: calc(var(--star-size) * 6);
    height: calc(var(--star-size) * 6);
  }

  .star-wrapper[data-star-type="classic"] .star-glow {
    background: radial-gradient(
      circle,
      var(--star-color) 0%,
      rgba(255,255,255,0) 70%
    );
    opacity: 0.5;
    transform: translate(-50%, -50%) scale(1.2);
  }

  .star-wrapper[data-star-type="point"] .star-glow {
    background: radial-gradient(
      circle,
      var(--star-color) 0%,
      rgba(255,255,255,0) 50%
    );
    opacity: 0.4;
    width: calc(var(--star-size) * 2.5);
    height: calc(var(--star-size) * 2.5);
  }
  
  /* Animations */
  @keyframes glowPulse {
    0% { opacity: 0.4; transform: translate(-50%, -50%) scale(0.9); }
    50% { opacity: 0.7; transform: translate(-50%, -50%) scale(1.1); }
    100% { opacity: 0.4; transform: translate(-50%, -50%) scale(0.9); }
  }
  
  @keyframes innerGlowPulse {
    0% { opacity: 0.4; r: 2.5; }
    50% { opacity: 0.6; r: 3.2; }
    100% { opacity: 0.4; r: 2.5; }
  }
  
  @keyframes haloBreathing {
    0% { transform: translate(-50%, -50%) scale(0.9); opacity: 0.4; }
    50% { transform: translate(-50%, -50%) scale(1.1); opacity: 0.6; }
    100% { transform: translate(-50%, -50%) scale(0.9); opacity: 0.4; }
  }

  @keyframes refractionTwinkle {
    0% { opacity: 0.2; }
    25% { opacity: 0.5; }
    50% { opacity: 0.3; }
    75% { opacity: 0.6; }
    100% { opacity: 0.2; }
  }
</style>