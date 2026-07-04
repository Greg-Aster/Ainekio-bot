<script>
  import { createEventDispatcher, onMount } from 'svelte';
  import { AUTO_MODE, DARK_MODE, LIGHT_MODE } from '@constants/constants.ts';
  
  // Props
  export let siteConfig;
  
  // Local state
  let themePreview = '';
  
  // Event dispatcher
  const dispatch = createEventDispatcher();
  
  // Initialize theme preview
  onMount(() => {
    updateThemePreview();
  });
  
  // Function to update theme preview
  function updateThemePreview() {
    themePreview = `hsl(${siteConfig.themeColor.hue}, 65%, 50%)`;
  }
  
  // Function to handle hue change
  function handleHueChange() {
    updateThemePreview();
    dispatch('change', siteConfig);
  }
</script>

<!-- Default LIGHT_DARK_AUTO Theme Settings -->
<div class="bg-neutral-50 dark:bg-neutral-800/50 p-5 rounded-lg border border-neutral-200 dark:border-neutral-700 mb-8">
  <h3 class="text-lg font-medium text-black/80 dark:text-white/80 mb-3">Default Theme Mode</h3>
  
  <div class="space-y-4">
    <p class="text-sm text-neutral-600 dark:text-neutral-400">
      Choose the default theme mode for new visitors. Users can still change this preference through the theme switcher.
    </p>
    
    <div class="flex flex-col space-y-2">
      <label class="inline-flex items-center">
        <input 
          type="radio" 
          name="defaultTheme" 
          value={LIGHT_MODE} 
          checked={siteConfig.defaultTheme === LIGHT_MODE} 
          on:change={() => {
            siteConfig.defaultTheme = LIGHT_MODE;
            dispatch('change', siteConfig);
          }}
          class="h-4 w-4 text-[var(--primary)] border-neutral-300 dark:border-neutral-600 focus:ring-[var(--primary)]" 
        />
        <span class="ml-2 flex items-center text-neutral-700 dark:text-neutral-300">
          <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 mr-1.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="5"></circle>
            <line x1="12" y1="1" x2="12" y2="3"></line>
            <line x1="12" y1="21" x2="12" y2="23"></line>
            <line x1="4.22" y1="4.22" x2="5.64" y2="5.64"></line>
            <line x1="18.36" y1="18.36" x2="19.78" y2="19.78"></line>
            <line x1="1" y1="12" x2="3" y2="12"></line>
            <line x1="21" y1="12" x2="23" y2="12"></line>
            <line x1="4.22" y1="19.78" x2="5.64" y2="18.36"></line>
            <line x1="18.36" y1="5.64" x2="19.78" y2="4.22"></line>
          </svg>
          Light Mode
        </span>
      </label>
      
      <label class="inline-flex items-center">
        <input 
          type="radio" 
          name="defaultTheme" 
          value={DARK_MODE} 
          checked={siteConfig.defaultTheme === DARK_MODE}
          on:change={() => {
            siteConfig.defaultTheme = DARK_MODE;
            dispatch('change', siteConfig);
          }}
          class="h-4 w-4 text-[var(--primary)] border-neutral-300 dark:border-neutral-600 focus:ring-[var(--primary)]" 
        />
        <span class="ml-2 flex items-center text-neutral-700 dark:text-neutral-300">
          <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 mr-1.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path>
          </svg>
          Dark Mode
        </span>
      </label>
      
      <label class="inline-flex items-center">
        <input 
          type="radio" 
          name="defaultTheme" 
          value={AUTO_MODE} 
          checked={siteConfig.defaultTheme === AUTO_MODE}
          on:change={() => {
            siteConfig.defaultTheme = AUTO_MODE;
            dispatch('change', siteConfig);
          }}
          class="h-4 w-4 text-[var(--primary)] border-neutral-300 dark:border-neutral-600 focus:ring-[var(--primary)]" 
        />
        <span class="ml-2 flex items-center text-neutral-700 dark:text-neutral-300">
          <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 mr-1.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="10"></circle>
            <path d="M12 8c-1.654 0-3 1.346-3 3v0c0 1.654 1.346 3 3 3h0c1.654 0 3-1.346 3-3v0c0-1.654-1.346-3-3-3z"></path>
          </svg>
          System/Auto Mode
        </span>
      </label>
    </div>
  </div>
</div>

<!-- Theme Color Settings -->
<div class="bg-neutral-50 dark:bg-neutral-800/50 p-5 rounded-lg border border-neutral-200 dark:border-neutral-700 mb-8">
  <h3 class="text-lg font-medium text-black/80 dark:text-white/80 mb-3">Theme Color</h3>
  
  <div class="space-y-4">
    <div class="flex items-center">
      <input 
        type="checkbox" 
        id="theme-fixed" 
        bind:checked={siteConfig.themeColor.fixed}
        on:change={() => dispatch('change', siteConfig)}
        class="h-4 w-4 text-[var(--primary)] border-neutral-300 dark:border-neutral-600 rounded" 
      />
      <label for="theme-fixed" class="ml-2 block text-sm text-neutral-700 dark:text-neutral-300">
        Use fixed theme color (don't allow user customization)
      </label>
    </div>
    
    <div>
      <label for="theme-hue" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-2">
        Base Hue (0-360)
      </label>
      <div class="flex items-center space-x-4">
        <input 
          type="range" 
          id="theme-hue" 
          min="0" 
          max="360" 
          step="1"
          bind:value={siteConfig.themeColor.hue}
          on:input={handleHueChange}
          class="flex-grow h-2 bg-neutral-200 dark:bg-neutral-700 rounded-lg appearance-none cursor-pointer" 
        />
        <input 
          type="number" 
          bind:value={siteConfig.themeColor.hue}
          on:input={handleHueChange}
          min="0" 
          max="360" 
          class="w-16 px-2 py-1 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm transition text-center" 
        />
      </div>
    </div>
    
    <!-- Color Preview -->
    <div class="pt-2">
      <label class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-2">
        Preview
      </label>
      <div class="flex flex-wrap gap-3">
        <div class="w-16 h-16 rounded-lg shadow-sm" style="background-color: {themePreview};"></div>
        <div class="flex flex-col justify-between">
          <div class="text-sm font-medium" style="color: {themePreview};">Text Color Sample</div>
          <button class="px-3 py-1 text-white text-sm rounded" style="background-color: {themePreview};">
            Button Example
          </button>
        </div>
      </div>
    </div>
    
    <!-- Common Colors Quick Select -->
    <div class="pt-4 border-t border-neutral-200 dark:border-neutral-700">
      <label class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-2">
        Quick Select
      </label>
      <div class="flex flex-wrap gap-2">
        {#each [0, 30, 60, 120, 180, 210, 240, 270, 300, 330] as hue}
          <button 
            class="w-8 h-8 rounded-full border-2 transition-transform hover:scale-110 focus:scale-110"
            style="background-color: hsl({hue}, 65%, 50%); border-color: {siteConfig.themeColor.hue === hue ? 'white' : 'transparent'};"
            on:click={() => {
              siteConfig.themeColor.hue = hue;
              handleHueChange();
            }}
            title={`Hue: ${hue}°`}
          ></button>
        {/each}
      </div>
    </div>
  </div>
</div>