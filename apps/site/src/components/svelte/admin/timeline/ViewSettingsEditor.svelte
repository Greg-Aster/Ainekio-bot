<script>
  import { createEventDispatcher } from 'svelte';
  
  // Props
  export let viewSettings;
  export let onUpdate;
  
  // Local state
  let settings = { ...viewSettings };
  
  // Create event dispatcher
  const dispatch = createEventDispatcher();
  
  // Handle form changes
  function handleChange() {
    onUpdate(settings);
    dispatch('change', settings);
  }
  
  // Reset to defaults
  function resetToDefaults() {
    if (confirm('Are you sure you want to reset all view settings to defaults?')) {
      settings = {
        defaultZoom: 1,
        maxZoom: 5,
        minZoom: 0.5,
        zoomStep: 0.2,
        padding: 15,
        zoomRatioThresholds: {
          verySmall: 50,
          small: 20,
          medium: 10,
          large: 4,
          veryLarge: 2
        },
        zoomLevels: {
          verySmall: 4,
          small: 3,
          medium: 2.5,
          large: 2,
          veryLarge: 1.5,
          full: 1.2
        }
      };
      handleChange();
    }
  }
</script>

<div class="view-settings-editor">
  <div class="mb-6">
    <h3 class="text-lg font-medium text-black/80 dark:text-white/80 mb-3">Timeline Visualization Settings</h3>
    <p class="text-neutral-600 dark:text-neutral-400 mb-4">
      Configure how the timeline is displayed and interacted with.
    </p>
  </div>
  
  <div class="grid grid-cols-1 md:grid-cols-2 gap-6 mb-8">
    <!-- Zoom Settings -->
    <div class="bg-neutral-50 dark:bg-neutral-800/50 p-4 rounded-lg border border-neutral-200 dark:border-neutral-700">
      <h4 class="font-medium text-black/80 dark:text-white/80 mb-3">Zoom Settings</h4>
      
      <div class="space-y-4">
        <div>
          <label for="default-zoom" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
            Default Zoom Level
          </label>
          <input 
            type="number" 
            id="default-zoom" 
            bind:value={settings.defaultZoom}
            on:change={handleChange}
            step="0.1"
            min="0.5"
            max="5"
            class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-l text-sm text-neutral-900 dark:text-neutral-100"
          />
          <p class="mt-1 text-xs text-neutral-500 dark:text-neutral-400">
            Initial zoom level when the timeline loads
          </p>
        </div>
        
        <div class="grid grid-cols-2 gap-4">
          <div>
            <label for="min-zoom" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
              Minimum Zoom
            </label>
            <input 
              type="number" 
              id="min-zoom" 
              bind:value={settings.minZoom}
              on:change={handleChange}
              step="0.1"
              min="0.1"
              max="1"
              class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-l text-sm text-neutral-900 dark:text-neutral-100"
            />
          </div>
          <div>
            <label for="max-zoom" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
              Maximum Zoom
            </label>
            <input 
              type="number" 
              id="max-zoom" 
              bind:value={settings.maxZoom}
              on:change={handleChange}
              step="0.1"
              min="1"
              max="10"
              class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-l text-sm text-neutral-900 dark:text-neutral-100"
            />
          </div>
        </div>
        
        <div>
          <label for="zoom-step" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
            Zoom Step
          </label>
          <input 
            type="number" 
            id="zoom-step" 
            bind:value={settings.zoomStep}
            on:change={handleChange}
            step="0.05"
            min="0.05"
            max="0.5"
            class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-l text-sm text-neutral-900 dark:text-neutral-100"
          />
          <p class="mt-1 text-xs text-neutral-500 dark:text-neutral-400">
            Amount to zoom in/out for each step
          </p>
        </div>
        
        <div>
          <label for="padding" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
            Padding (%)
          </label>
          <input 
            type="number" 
            id="padding" 
            bind:value={settings.padding}
            on:change={handleChange}
            step="1"
            min="0"
            max="50"
            class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-l text-sm text-neutral-900 dark:text-neutral-100"
          />
          <p class="mt-1 text-xs text-neutral-500 dark:text-neutral-400">
            Percentage padding on timeline edges
          </p>
        </div>
      </div>
    </div>
    
    <!-- Zoom Ratio Thresholds -->
    <div class="bg-neutral-50 dark:bg-neutral-800/50 p-4 rounded-lg border border-neutral-200 dark:border-neutral-700">
      <h4 class="font-medium text-black/80 dark:text-white/80 mb-3">Zoom Ratio Thresholds</h4>
      <p class="text-xs text-neutral-500 dark:text-neutral-400 mb-3">
        These thresholds determine how events are displayed at different zoom levels.
      </p>
      
      <div class="space-y-3">
        <div>
          <label for="very-small-threshold" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
            Very Small Threshold
          </label>
          <input 
            type="number" 
            id="very-small-threshold" 
            bind:value={settings.zoomRatioThresholds.verySmall}
            on:change={handleChange}
            class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-l text-sm text-neutral-900 dark:text-neutral-100"
          />
          <p class="mt-1 text-xs text-neutral-500 dark:text-neutral-400">
            &lt; {1/settings.zoomRatioThresholds.verySmall * 100}% of timeline visible
          </p>
        </div>
        
        <div>
          <label for="small-threshold" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
            Small Threshold
          </label>
          <input 
            type="number" 
            id="small-threshold" 
            bind:value={settings.zoomRatioThresholds.small}
            on:change={handleChange}
            class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-l text-sm text-neutral-900 dark:text-neutral-100"
          />
          <p class="mt-1 text-xs text-neutral-500 dark:text-neutral-400">
            {1/settings.zoomRatioThresholds.verySmall * 100}% - {1/settings.zoomRatioThresholds.small * 100}% of timeline visible
          </p>
        </div>
        
        <div>
          <label for="medium-threshold" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
            Medium Threshold
          </label>
          <input 
            type="number" 
            id="medium-threshold" 
            bind:value={settings.zoomRatioThresholds.medium}
            on:change={handleChange}
            class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-l text-sm text-neutral-900 dark:text-neutral-100"
          />
          <p class="mt-1 text-xs text-neutral-500 dark:text-neutral-400">
            {1/settings.zoomRatioThresholds.small * 100}% - {1/settings.zoomRatioThresholds.medium * 100}% of timeline visible
          </p>
        </div>
        
        <div>
          <label for="large-threshold" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
            Large Threshold
          </label>
          <input 
            type="number" 
            id="large-threshold" 
            bind:value={settings.zoomRatioThresholds.large}
            on:change={handleChange}
            class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-l text-sm text-neutral-900 dark:text-neutral-100"
          />
          <p class="mt-1 text-xs text-neutral-500 dark:text-neutral-400">
            {1/settings.zoomRatioThresholds.medium * 100}% - {1/settings.zoomRatioThresholds.large * 100}% of timeline visible
          </p>
        </div>
        
        <div>
          <label for="very-large-threshold" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
            Very Large Threshold
          </label>
          <input 
            type="number" 
            id="very-large-threshold" 
            bind:value={settings.zoomRatioThresholds.veryLarge}
            on:change={handleChange}
            class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-l text-sm text-neutral-900 dark:text-neutral-100"
          />
          <p class="mt-1 text-xs text-neutral-500 dark:text-neutral-400">
            {1/settings.zoomRatioThresholds.large * 100}% - {1/settings.zoomRatioThresholds.veryLarge * 100}% of timeline visible
          </p>
        </div>
      </div>
    </div>
  </div>
  
  <!-- Zoom Levels -->
  <div class="bg-neutral-50 dark:bg-neutral-800/50 p-4 rounded-lg border border-neutral-200 dark:border-neutral-700 mb-6">
    <h4 class="font-medium text-black/80 dark:text-white/80 mb-3">Zoom Levels</h4>
    <p class="text-xs text-neutral-500 dark:text-neutral-400 mb-3">
      These settings control the zoom level for each visibility threshold.
    </p>
    
    <div class="grid grid-cols-2 md:grid-cols-3 gap-4">
      <div>
        <label for="very-small-zoom" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
          Very Small Zoom
        </label>
        <input 
          type="number" 
          id="very-small-zoom" 
          bind:value={settings.zoomLevels.verySmall}
          on:change={handleChange}
          step="0.1"
          min="1"
          max="10"
          class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-l text-sm text-neutral-900 dark:text-neutral-100"
        />
      </div>
      
      <div>
        <label for="small-zoom" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
          Small Zoom
        </label>
        <input 
          type="number" 
          id="small-zoom" 
          bind:value={settings.zoomLevels.small}
          on:change={handleChange}
          step="0.1"
          min="1"
          max="10"
          class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-l text-sm text-neutral-900 dark:text-neutral-100"
        />
      </div>
      
      <div>
        <label for="medium-zoom" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
          Medium Zoom
        </label>
        <input 
          type="number" 
          id="medium-zoom" 
          bind:value={settings.zoomLevels.medium}
          on:change={handleChange}
          step="0.1"
          min="1"
          max="10"
          class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-l text-sm text-neutral-900 dark:text-neutral-100"
        />
      </div>
      
      <div>
        <label for="large-zoom" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
          Large Zoom
        </label>
        <input 
          type="number" 
          id="large-zoom" 
          bind:value={settings.zoomLevels.large}
          on:change={handleChange}
          step="0.1"
          min="1"
          max="10"
          class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-l text-sm text-neutral-900 dark:text-neutral-100"
        />
      </div>
      
      <div>
        <label for="very-large-zoom" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
          Very Large Zoom
        </label>
        <input 
          type="number" 
          id="very-large-zoom" 
          bind:value={settings.zoomLevels.veryLarge}
          on:change={handleChange}
          step="0.1"
          min="1"
          max="10"
          class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-l text-sm text-neutral-900 dark:text-neutral-100"
        />
      </div>
      
      <div>
        <label for="full-zoom" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
          Full Zoom
        </label>
        <input 
          type="number" 
          id="full-zoom" 
          bind:value={settings.zoomLevels.full}
          on:change={handleChange}
          step="0.1"
          min="1"
          max="10"
          class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-l text-sm text-neutral-900 dark:text-neutral-100"
        />
      </div>
    </div>
  </div>
  
  <!-- Reset Button -->
  <div class="flex justify-end">
    <button 
      type="button"
      class="px-4 py-2 bg-neutral-200 dark:bg-neutral-700 text-neutral-800 dark:text-neutral-200 font-medium rounded-md hover:bg-neutral-300 dark:hover:bg-neutral-600 transition-colors"
      on:click={resetToDefaults}
    >
      Reset to Defaults
    </button>
  </div>
</div>