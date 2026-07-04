<script>
    import { createEventDispatcher } from 'svelte';
    
    // Props
    export let siteConfig;
    
    // Initialize transparency setting if it doesn't exist
    if (siteConfig.transparency === undefined) {
      siteConfig.transparency = 0.9;
    }
    
    // Event dispatcher
    const dispatch = createEventDispatcher();
    
    // Handle input changes
    function handleChange() {
      dispatch('change', siteConfig);
    }
  </script>
  
  <div class="bg-neutral-50 dark:bg-neutral-800/50 p-5 rounded-lg border border-neutral-200 dark:border-neutral-700 mb-8">
    <h3 class="text-lg font-medium text-black/80 dark:text-white/80 mb-3">Content Transparency</h3>
    
    <div class="space-y-4">
      <p class="text-sm text-neutral-600 dark:text-neutral-400">
        Adjust transparency level to create a layered effect with your background.
      </p>
      
      <!-- Background Transparency -->
      <div>
        <label for="bg-opacity" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-2">
          Background Transparency: {Math.round((1-siteConfig.transparency) * 100)}%
        </label>
        <div class="flex items-center space-x-4">
          <input 
            type="range" 
            id="bg-opacity" 
            min="0.5" 
            max="1" 
            step="0.05"
            bind:value={siteConfig.transparency}
            on:input={handleChange}
            class="flex-grow h-2 bg-neutral-200 dark:bg-neutral-700 rounded-lg appearance-none cursor-pointer" 
          />
        </div>
      </div>
    </div>
  </div>