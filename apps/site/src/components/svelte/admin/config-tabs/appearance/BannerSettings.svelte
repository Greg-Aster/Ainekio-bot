<script>
  import { createEventDispatcher, onMount } from 'svelte';
  
  // Props
  export let bannerConfig;

  // Initialize navbarSpacing if it doesn't exist
  if (!bannerConfig.navbarSpacing) {
    bannerConfig.navbarSpacing = {
      standard: '0',
      timeline: '4.5rem',
      video: '4.5rem',
      image: '4.5rem'
    };
  }
  
  // Local state
  let isBannerSequence = false;
  let bannerCount = 0;
  let selectedBannerIndex = 0;
  let imageBaseUrl = '/src/assets/banner/'; // Base URL for serving images
  
  // Event dispatcher
  const dispatch = createEventDispatcher();
  
  // Helper functions for paths
  function getDisplayPath(path) {
    // Return just the filename part for display purposes
    if (!path) return '';
    const filename = path.split('/').pop();
    return filename;
  }
  
  // Handle changes to configuration
  function handleChange() {
    dispatch('change', bannerConfig);
  }
  
  // Convert import path to URL path
  function getImageUrl(path) {
    if (!path) return null;
    
    // Extract the filename - handle both formats:
    // 1. "src/assets/banner/0001.png" (from configuration)
    // 2. Object format (when imported in the TypeScript file)
    let filename;
    if (typeof path === 'string') {
      filename = path.split('/').pop();
    } else if (path && path.toString) {
      const pathStr = path.toString();
      filename = pathStr.split('/').pop();
    } else {
      return null;
    }
    
    return `${imageBaseUrl}${filename}`;
  }
  
  // Initialize from bannerConfig on mount
  onMount(() => {
    // Check if we have a sequence or single banner
    if (bannerConfig && bannerConfig.bannerList) {
      isBannerSequence = bannerConfig.bannerList.length > 1;
      bannerCount = bannerConfig.bannerList.length;
      
      // Set the selected banner index to match the default banner
      if (isBannerSequence && bannerConfig.defaultBanner) {
        const defaultBannerStr = bannerConfig.defaultBanner.toString();
        const foundIndex = bannerConfig.bannerList.findIndex(banner => 
          banner.toString() === defaultBannerStr
        );
        if (foundIndex >= 0) {
          selectedBannerIndex = foundIndex;
        }
      }
    }
    
    // Initialize default banner type if it doesn't exist
    if (!bannerConfig.defaultBannerType) {
      bannerConfig.defaultBannerType = 'standard';
    }
    
    // Initialize default banner data if it doesn't exist
    if (!bannerConfig.defaultBannerData) {
      bannerConfig.defaultBannerData = {};
    }
    
    // Initialize navbar spacing if it doesn't exist
    if (!bannerConfig.navbarSpacing) {
      bannerConfig.navbarSpacing = {
        standard: '0',
        timeline: '4.5rem',
        video: '4.5rem',
        image: '4.5rem'
      };
    }
  });
  
  // Function to toggle banner type
  function toggleBannerType() {
    isBannerSequence = !isBannerSequence;
    
    if (!isBannerSequence && bannerConfig.bannerList.length > 0) {
      // If switching to single banner, keep only the default banner
      bannerConfig.bannerList = [bannerConfig.defaultBanner];
      bannerConfig.animation.enabled = false;
    } else if (isBannerSequence) {
      // If switching to sequence, enable animation
      bannerConfig.animation.enabled = true;
    }
    
    handleChange();
  }
  
  // Function to select a banner from the sequence
  function selectBanner(index) {
    selectedBannerIndex = index;
    // Update the default banner
    bannerConfig.defaultBanner = bannerConfig.bannerList[index];
    handleChange();
  }
  
  // Function to remove banner from sequence
  function removeBannerFromSequence(index) {
    if (bannerConfig.bannerList.length <= 1) {
      alert("Cannot remove the only banner in the sequence");
      return;
    }
    
    // Remove banner from list
    bannerConfig.bannerList = bannerConfig.bannerList.filter((_, i) => i !== index);
    
    // If we removed the default banner, set a new default
    if (selectedBannerIndex === index) {
      selectedBannerIndex = 0;
      bannerConfig.defaultBanner = bannerConfig.bannerList[0];
    } else if (selectedBannerIndex > index) {
      // Adjust selectedBannerIndex if we removed a banner before it
      selectedBannerIndex--;
    }
    
    bannerCount = bannerConfig.bannerList.length;
    handleChange();
  }
  
  // Function to handle default banner type change
  function handleDefaultBannerTypeChange(event) {
    const newType = event.target.value;
    bannerConfig.defaultBannerType = newType;
    
    // Reset banner data when type changes
    if (newType === 'standard') {
      bannerConfig.defaultBannerData = {};
    } else if (newType === 'video') {
      bannerConfig.defaultBannerData = { videoId: '' };
    } else if (newType === 'image') {
      bannerConfig.defaultBannerData = { imageUrl: '' };
    } else if (newType === 'timeline') {
      bannerConfig.defaultBannerData = { 
        category: '', 
        title: '', 
        startYear: null, 
        endYear: null,
        background: '/public/posts/timeline/universe.png',
        compact: false,
        height: '70vh'
      };
    }
    
    handleChange();
  }
</script>

<!-- Banner Settings -->
<div class="bg-neutral-50 dark:bg-neutral-800/50 p-5 rounded-lg border border-neutral-200 dark:border-neutral-700 mb-8">
  <h3 class="text-lg font-medium text-black/80 dark:text-white/80 mb-3">Banner Settings</h3>
  
  <!-- Default Banner Type Selection -->
  <div class="mb-6 pt-0 pb-4 border-b border-neutral-200 dark:border-neutral-700">
    <h4 class="text-md font-medium text-black/80 dark:text-white/80 mb-3">Default Banner Type</h4>
    
    <div class="space-y-4">
      <div>
        <label for="default-banner-type" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
          Choose the banner type for the main page
        </label>
        <select 
            id="default-banner-type" 
            bind:value={bannerConfig.defaultBannerType}
            on:change={handleDefaultBannerTypeChange}
            class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm text-neutral-900 dark:text-neutral-100"
          >
            <option value="standard">Standard (Animated images)</option>
            <option value="video">Video</option>
            <option value="image">Single Image</option>
            <option value="timeline">Timeline</option>
        </select>
        <p class="mt-1 text-xs text-neutral-500 dark:text-neutral-400">
          This banner type will be used on the main page and any page that doesn't specify its own banner.
        </p>
      </div>
      
      <!-- Video Banner Settings (only show if video type is selected) -->
      {#if bannerConfig.defaultBannerType === 'video'}
        <div class="p-4 bg-neutral-100 dark:bg-neutral-700/30 rounded-md">
          <h5 class="text-sm font-medium text-black/80 dark:text-white/80 mb-3">Video Banner Settings</h5>
          
          <div>
            <label for="video-id" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
              YouTube Video ID
            </label>
            <input 
              type="text" 
              id="video-id" 
              bind:value={bannerConfig.defaultBannerData.videoId}
              on:input={handleChange}
              class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm text-neutral-800 dark:text-neutral-200"
              placeholder="e.g., dQw4w9WgXcQ"
            />
            <p class="mt-1 text-xs text-neutral-500 dark:text-neutral-400">
              Enter the YouTube video ID (the part after ?v= in the YouTube URL)
            </p>
          </div>
        </div>
      {/if}
      
      <!-- Image Banner Settings (only show if image type is selected) -->
      {#if bannerConfig.defaultBannerType === 'image'}
        <div class="p-4 bg-neutral-100 dark:bg-neutral-700/30 rounded-md">
          <h5 class="text-sm font-medium text-black/80 dark:text-white/80 mb-3">Image Banner Settings</h5>
          
          <div>
            <label for="image-url" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
              Image URL
            </label>
            <select 
                id="image-url" 
                bind:value={bannerConfig.defaultBannerData.imageUrl}
                on:change={handleChange}
                class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm text-neutral-800 dark:text-neutral-200"
              >
                <option value="" class="text-neutral-900 dark:text-neutral-100">Select an image</option>
                <option value="/src/assets/banner/0001.png" class="text-neutral-900 dark:text-neutral-100">0001.png</option>
                <option value="/src/assets/banner/0002.png" class="text-neutral-900 dark:text-neutral-100">0002.png</option>
                <option value="/src/assets/banner/0003.png" class="text-neutral-900 dark:text-neutral-100">0003.png</option>
                <option value="/src/assets/banner/0004.png" class="text-neutral-900 dark:text-neutral-100">0004.png</option>
                <option value="/src/assets/banner/0005.png" class="text-neutral-900 dark:text-neutral-100">0005.png</option>
                <option value="/src/assets/banner/0006.png" class="text-neutral-900 dark:text-neutral-100">0006.png</option>
                <option value="/src/assets/banner/0007.png" class="text-neutral-900 dark:text-neutral-100">0007.png</option>
                <option value="/src/assets/banner/0008.png" class="text-neutral-900 dark:text-neutral-100">0008.png</option>
            </select>
            <p class="mt-1 text-xs text-neutral-500 dark:text-neutral-400">
              Select the image to use for the banner
            </p>
          </div>
        </div>
      {/if}
      
      <!-- Timeline Banner Settings (only show if timeline type is selected) -->
      {#if bannerConfig.defaultBannerType === 'timeline'}
        <div class="p-4 bg-neutral-100 dark:bg-neutral-700/30 rounded-md">
          <h5 class="text-sm font-medium text-black/80 dark:text-white/80 mb-3">Timeline Banner Settings</h5>
          
          <div class="space-y-4">
            <div>
              <label for="timeline-category" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
                Category
              </label>
              <input 
                type="text" 
                id="timeline-category" 
                bind:value={bannerConfig.defaultBannerData.category}
                on:input={handleChange}
                class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm text-neutral-800 dark:text-neutral-200"
                placeholder="e.g., history, science, etc."
                required
              />
              <p class="mt-1 text-xs text-neutral-500 dark:text-neutral-400">
                Category is required for timeline banners
              </p>
            </div>
            
            <div>
              <label for="timeline-title" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
                Title (optional)
              </label>
              <input 
                type="text" 
                id="timeline-title" 
                bind:value={bannerConfig.defaultBannerData.title}
                on:input={handleChange}
                class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm text-neutral-800 dark:text-neutral-200"
                placeholder="Timeline title"
              />
            </div>
            
            <div class="grid grid-cols-2 gap-4">
              <div>
                <label for="timeline-start-year" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
                  Start Year
                </label>
                <input 
                  type="number" 
                  id="timeline-start-year" 
                  bind:value={bannerConfig.defaultBannerData.startYear}
                  on:input={handleChange}
                  class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm text-neutral-800 dark:text-neutral-200"
                  placeholder="e.g., 1900"
                />
              </div>
              
              <div>
                <label for="timeline-end-year" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
                  End Year
                </label>
                <input 
                  type="number" 
                  id="timeline-end-year" 
                  bind:value={bannerConfig.defaultBannerData.endYear}
                  on:input={handleChange}
                  class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm text-neutral-800 dark:text-neutral-200"
                  placeholder="e.g., 2023"
                />
              </div>
            </div>
            
            <div>
              <label for="timeline-background" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
                Background Image (optional)
              </label>
              <input 
                type="text" 
                id="timeline-background" 
                bind:value={bannerConfig.defaultBannerData.background}
                on:input={handleChange}
                class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm text-neutral-800 dark:text-neutral-200"
                placeholder="/public/posts/timeline/universe.png"
              />
              <p class="mt-1 text-xs text-neutral-500 dark:text-neutral-400">
                Path to the background image for the timeline
              </p>
            </div>
            
            <div class="flex items-center">
              <input 
                type="checkbox" 
                id="timeline-compact" 
                bind:checked={bannerConfig.defaultBannerData.compact}
                on:change={handleChange}
                class="h-4 w-4 text-[var(--primary)] border-neutral-300 dark:border-neutral-600 rounded" 
              />
              <label for="timeline-compact" class="ml-2 block text-sm text-neutral-700 dark:text-neutral-300">
                Compact Mode
              </label>
            </div>
            
            <div>
              <label for="timeline-height" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
                Timeline Height
              </label>
              <input 
                type="text" 
                id="timeline-height" 
                bind:value={bannerConfig.defaultBannerData.height}
                on:input={handleChange}
                class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm text-neutral-800 dark:text-neutral-200"
                placeholder="70vh"
              />
              <p class="mt-1 text-xs text-neutral-500 dark:text-neutral-400">
                CSS value for timeline height (vh units recommended)
              </p>
            </div>
          </div>
        </div>
      {/if}
      
      <div class="p-3 bg-blue-50 dark:bg-blue-900/20 rounded-md text-sm text-blue-800 dark:text-blue-200">
        <p>The selected banner type will be used for the main page and pages without a specific banner. Post pages can still override this with their own banner settings.</p>
      </div>
    </div>
  </div>
  
  <!-- Standard Banner Settings Section -->
  {#if bannerConfig.defaultBannerType === 'standard'}
  <div class="space-y-6">
    <!-- Standard Banner Image Selection (only show for standard banner type) -->
    <div>
      <h4 class="text-md font-medium text-black/80 dark:text-white/80 mb-3">Banner Images</h4>
      
      <div class="space-y-4">
        <!-- Banner Preview -->
        <div class="w-full h-40 bg-neutral-200 dark:bg-neutral-700 rounded-lg overflow-hidden mb-3 relative">
          {#if bannerConfig.defaultBanner}
            <!-- Try to show the actual image if possible -->
            <div class="w-full h-full flex items-center justify-center">
              <div class="absolute inset-0 bg-gradient-to-r from-blue-500 to-purple-500 opacity-20"></div>
              <p class="text-center p-4 relative z-10 bg-black/30 text-white rounded-md shadow-lg">
                Selected Banner:<br>
                <span class="font-medium">{getDisplayPath(bannerConfig.defaultBanner)}</span>
              </p>
            </div>
          {:else}
            <div class="w-full h-full flex items-center justify-center">
              <svg xmlns="http://www.w3.org/2000/svg" class="h-16 w-16 text-neutral-400 dark:text-neutral-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
              </svg>
              <p class="ml-2 text-neutral-500">No banner selected</p>
            </div>
          {/if}
        </div>
        
        <!-- Banner Type Toggle -->
        <div class="flex items-center space-x-2">
          <span class="text-sm text-neutral-700 dark:text-neutral-300">Banner Type:</span>
          <label class="inline-flex items-center">
            <input 
              type="radio" 
              name="bannerType" 
              checked={!isBannerSequence} 
              on:change={toggleBannerType}
              class="h-4 w-4 text-[var(--primary)] border-neutral-300 dark:border-neutral-600" 
            />
            <span class="ml-1 text-sm text-neutral-600 dark:text-neutral-400">Static</span>
          </label>
          <label class="inline-flex items-center">
            <input 
              type="radio" 
              name="bannerType" 
              checked={isBannerSequence} 
              on:change={toggleBannerType}
              class="h-4 w-4 text-[var(--primary)] border-neutral-300 dark:border-neutral-600" 
            />
            <span class="ml-1 text-sm text-neutral-600 dark:text-neutral-400">Animated Sequence</span>
          </label>
        </div>
        
        <!-- Banner Selection Dropdown -->
        <div>
          <select 
              class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm text-neutral-800 dark:text-neutral-200"
            on:change={(e) => {
              const path = e.target.value;
              if (path) {
                bannerConfig.defaultBanner = path;
                
                if (!isBannerSequence) {
                  bannerConfig.bannerList = [path];
                }
                
                handleChange();
              }
            }}
          >
            <option value="" class="text-neutral-900 dark:text-neutral-100">Select a banner image</option>
            <option value="src/assets/banner/0001.png"class="text-neutral-900 dark:text-neutral-100">0001.png</option>
            <option value="src/assets/banner/0002.png"class="text-neutral-900 dark:text-neutral-100">0002.png</option>
            <option value="src/assets/banner/0003.png"class="text-neutral-900 dark:text-neutral-100">0003.png</option>
            <option value="src/assets/banner/0004.png"class="text-neutral-900 dark:text-neutral-100">0004.png</option>
            <option value="src/assets/banner/0005.png"class="text-neutral-900 dark:text-neutral-100">0005.png</option>
            <option value="src/assets/banner/0006.png"class="text-neutral-900 dark:text-neutral-100">0006.png</option>
            <option value="src/assets/banner/0007.png"class="text-neutral-900 dark:text-neutral-100">0007.png</option>
            <option value="src/assets/banner/0008.png"class="text-neutral-900 dark:text-neutral-100">0008.png</option>
          </select>
          <p class="mt-1 text-xs text-neutral-500 dark:text-neutral-400">
            Choose a banner image from your project assets
          </p>
        </div>
        
        <!-- Banner Sequence Controls (if sequence mode) -->
        {#if isBannerSequence}
          <div class="pt-3 border-t border-neutral-200 dark:border-neutral-700 space-y-3">
            <h4 class="text-sm font-medium text-black/80 dark:text-white/80">Banner Sequence</h4>
            
            <!-- Sequence Preview -->
            <div class="flex flex-wrap gap-2">
              {#each bannerConfig.bannerList as banner, index}
                <div class="relative group">
                  <div 
                    class="w-24 h-16 bg-neutral-200 dark:bg-neutral-700 rounded-md overflow-hidden cursor-pointer border-2 border-transparent hover:border-[var(--primary)] transition-colors flex-shrink-0 flex items-center justify-center"
                    class:border-[var(--primary)]={selectedBannerIndex === index}
                    on:click={() => selectBanner(index)}
                  >
                    <!-- Show a color block with filename -->
                    <div class="w-full h-full flex items-center justify-center bg-gradient-to-r from-blue-500 to-purple-500 text-white text-xs p-1 text-center">
                      {getDisplayPath(banner)}
                    </div>
                  </div>
                  
                  <!-- Remove button -->
                  <button
                    class="absolute -top-2 -right-2 w-6 h-6 rounded-full bg-red-500 text-white flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"
                    title="Remove from sequence"
                    on:click={() => removeBannerFromSequence(index)}
                  >
                    <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
                      <path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd" />
                    </svg>
                  </button>
                </div>
              {/each}
            </div>
            
            <!-- Add to Sequence -->
            <div>
              <select 
    class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm text-neutral-800 dark:text-neutral-200"
                on:change={(e) => {
                  const path = e.target.value;
                  if (path && !bannerConfig.bannerList.includes(path)) {
                    bannerConfig.bannerList = [...bannerConfig.bannerList, path];
                    bannerCount = bannerConfig.bannerList.length;
                    handleChange();
                  }
                  // Reset the select to the placeholder
                  e.target.value = "";
                }}
              >
                <option value="" class="text-neutral-900 dark:text-neutral-100">Add banner to sequence...</option>
                <option value="src/assets/banner/0001.png" class="text-neutral-900 dark:text-neutral-100">0001.png</option>
                <option value="src/assets/banner/0002.png" class="text-neutral-900 dark:text-neutral-100">0002.png</option>
                <option value="src/assets/banner/0003.png" class="text-neutral-900 dark:text-neutral-100">0003.png</option>
                <option value="src/assets/banner/0004.png" class="text-neutral-900 dark:text-neutral-100">0004.png</option>
                <option value="src/assets/banner/0005.png" class="text-neutral-900 dark:text-neutral-100">0005.png</option>
                <option value="src/assets/banner/0006.png" class="text-neutral-900 dark:text-neutral-100">0006.png</option>
                <option value="src/assets/banner/0007.png" class="text-neutral-900 dark:text-neutral-100">0007.png</option>
                <option value="src/assets/banner/0008.png" class="text-neutral-900 dark:text-neutral-100">0008.png</option>
              </select>
              <p class="mt-1 text-xs text-neutral-500 dark:text-neutral-400">
                Select banners to add to the animation sequence
              </p>
            </div>
            
            <!-- Banner Sequence Order Info -->
            <div class="p-3 bg-blue-50 dark:bg-blue-900/20 rounded-md text-sm text-blue-800 dark:text-blue-200">
              <p>The banner marked with a highlighted border is your default banner. It will be shown first in the animation sequence.</p>
            </div>
          </div>
        {/if}
      </div>
    </div>
    
    <!-- Animation Settings (only for standard banner type) -->
    <div>
      <h4 class="text-md font-medium text-black/80 dark:text-white/80 mb-3">Animation Settings</h4>
      
      <div class="space-y-4">
        <div class="flex items-center">
          <input 
            type="checkbox" 
            id="banner-animation-enabled" 
            bind:checked={bannerConfig.animation.enabled}
            on:change={handleChange}
            class="h-4 w-4 text-[var(--primary)] border-neutral-300 dark:border-neutral-600 rounded" 
            disabled={!isBannerSequence}
          />
          <label for="banner-animation-enabled" class="ml-2 block text-sm text-neutral-700 dark:text-neutral-300">
            Enable Banner Animation
            {#if !isBannerSequence}
              <span class="text-neutral-500 dark:text-neutral-400">(Requires Sequence Mode)</span>
            {/if}
          </label>
        </div>
        
        <div>
          <label for="banner-animation-interval" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
            Animation Interval (ms)
          </label>
          <div class="flex items-center space-x-4">
            <input 
              type="range" 
              id="banner-animation-interval" 
              min="1000" 
              max="10000" 
              step="500"
              bind:value={bannerConfig.animation.interval}
              on:input={handleChange}
              class="flex-grow h-2 bg-neutral-200 dark:bg-neutral-700 rounded-lg appearance-none cursor-pointer" 
              disabled={!bannerConfig.animation.enabled || !isBannerSequence}
            />
            <input 
              type="number" 
              bind:value={bannerConfig.animation.interval}
              on:input={handleChange}
              min="1000" 
              max="10000" 
              step="500"
              class="w-24 px-2 py-1 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm transition text-center" 
              disabled={!bannerConfig.animation.enabled || !isBannerSequence}
            />
          </div>
        </div>
        
        <div>
          <label for="banner-transition-duration" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
            Transition Duration (ms)
          </label>
          <div class="flex items-center space-x-4">
            <input 
              type="range" 
              id="banner-transition-duration" 
              min="100" 
              max="2000" 
              step="100"
              bind:value={bannerConfig.animation.transitionDuration}
              on:input={handleChange}
              class="flex-grow h-2 bg-neutral-200 dark:bg-neutral-700 rounded-lg appearance-none cursor-pointer" 
              disabled={!bannerConfig.animation.enabled || !isBannerSequence}
            />
            <input 
              type="number" 
              bind:value={bannerConfig.animation.transitionDuration}
              on:input={handleChange}
              min="100" 
              max="2000" 
              step="100"
              class="w-24 px-2 py-1 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm transition text-center" 
              disabled={!bannerConfig.animation.enabled || !isBannerSequence}
            />
          </div>
        </div>
        
        <div>
          <label for="banner-animation-direction" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
            Animation Direction
          </label>
          <select 
            id="banner-animation-direction" 
            bind:value={bannerConfig.animation.direction}
            on:change={handleChange}
            class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm text-neutral-900 dark:text-neutral-100"
            disabled={!bannerConfig.animation.enabled || !isBannerSequence}
          >
            <option value="forward">Forward</option>
            <option value="reverse">Reverse</option>
            <option value="alternate">Alternate</option>
          </select>
        </div>
      </div>
    </div>
    
    <!-- Visual Settings (only for standard and image banner types) -->
    <div>
      <h4 class="text-md font-medium text-black/80 dark:text-white/80 mb-3">Visual Settings</h4>
      
      <div class="space-y-4">
        <div>
          <label for="banner-object-fit" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
            Image Fit
          </label>
          <select 
            id="banner-object-fit" 
            bind:value={bannerConfig.visual.objectFit}
            on:change={handleChange}
            class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm text-neutral-900 dark:text-neutral-100"
          >
            <option value="cover">Cover</option>
            <option value="contain">Contain</option>
            <option value="fill">Fill</option>
          </select>
        </div>
        
        <div>
          <label for="banner-object-position" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
            Image Position
          </label>
          <input 
            type="text" 
            id="banner-object-position" 
            bind:value={bannerConfig.visual.objectPosition}
            on:input={handleChange}
              class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm text-neutral-800 dark:text-neutral-200"
            placeholder="e.g., center"
          />
        </div>
        
        <div>
          <label for="banner-border-radius" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
            Border Radius
          </label>
          <input 
            type="text" 
            id="banner-border-radius" 
            bind:value={bannerConfig.visual.borderRadius}
            on:input={handleChange}
              class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm text-neutral-800 dark:text-neutral-200"
            placeholder="e.g., 0.5rem"
          />
        </div>
        
        <div class="flex items-center">
          <input 
            type="checkbox" 
            id="banner-apply-gradient" 
            bind:checked={bannerConfig.visual.applyGradientOverlay}
            on:change={handleChange}
            class="h-4 w-4 text-[var(--primary)] border-neutral-300 dark:border-neutral-600 rounded" 
          />
          <label for="banner-apply-gradient" class="ml-2 block text-sm text-neutral-700 dark:text-neutral-300">
            Apply Gradient Overlay
          </label>
        </div>
        
        <div>
          <label for="banner-gradient-overlay" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
            Gradient Overlay
          </label>
          <input 
            type="text" 
            id="banner-gradient-overlay" 
            bind:value={bannerConfig.visual.gradientOverlay}
            on:input={handleChange}
              class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm text-neutral-800 dark:text-neutral-200"
            placeholder="e.g., linear-gradient(to bottom, rgba(0,0,0,0.2), transparent)"
            disabled={!bannerConfig.visual.applyGradientOverlay}
          />
        </div>
      </div>
    </div>
    
    <!-- Fallback Settings (only for standard banner type) -->
    <div>
      <h4 class="text-md font-medium text-black/80 dark:text-white/80 mb-3">Fallback Settings</h4>
      
      <div class="space-y-4">
        <div class="flex items-center">
          <input 
            type="checkbox" 
            id="banner-fallback-enabled" 
            bind:checked={bannerConfig.fallback.enabled}
            on:change={handleChange}
            class="h-4 w-4 text-[var(--primary)] border-neutral-300 dark:border-neutral-600 rounded" 
          />
          <label for="banner-fallback-enabled" class="ml-2 block text-sm text-neutral-700 dark:text-neutral-300">
            Enable Fallback
          </label>
        </div>
        
        <div>
          <label for="banner-fallback-type" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
            Fallback Type
          </label>
          <select 
            id="banner-fallback-type" 
            bind:value={bannerConfig.fallback.type}
            on:change={handleChange}
            class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm text-neutral-900 dark:text-neutral-100"
            disabled={!bannerConfig.fallback.enabled}
          >
            <option value="color">Solid Color</option>
            <option value="gradient">Gradient</option>
          </select>
        </div>
        
        <div>
          <label for="banner-fallback-value" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
            Fallback Value
          </label>
          <input 
            type="text" 
            id="banner-fallback-value" 
            bind:value={bannerConfig.fallback.value}
            on:input={handleChange}
              class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm text-neutral-800 dark:text-neutral-200"
            placeholder="e.g., #f8f9fa or linear-gradient(...)"
            disabled={!bannerConfig.fallback.enabled}
          />
        </div>
      </div>
    </div>
  </div>
  {/if}
  
  <!-- Layout Settings (for all banner types) -->
  <div class="space-y-4 pt-6 mt-6 border-t border-neutral-200 dark:border-neutral-700">
    <h4 class="text-md font-medium text-black/80 dark:text-white/80 mb-3">Layout Settings</h4>
    
    <div class="space-y-4">
      <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div>
          <label for="banner-height-desktop" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
            Desktop Height
          </label>
          <input 
            type="text" 
            id="banner-height-desktop" 
            bind:value={bannerConfig.layout.height.desktop}
            on:input={handleChange}
            class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm text-neutral-800 dark:text-neutral-200"
            placeholder="e.g., 50vh"
          />
        </div>
        <div>
          <label for="banner-height-mobile" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
            Mobile Height
          </label>
          <input 
            type="text" 
            id="banner-height-mobile" 
            bind:value={bannerConfig.layout.height.mobile}
            on:input={handleChange}
            class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm text-neutral-800 dark:text-neutral-200"
            placeholder="e.g., 30vh"
          />
        </div>
      </div>
      
      <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div>
          <label for="banner-overlap-desktop" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
            Desktop Content Overlap
          </label>
          <input 
            type="text" 
            id="banner-overlap-desktop" 
            bind:value={bannerConfig.layout.overlap.desktop}
            on:input={handleChange}
            class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm text-neutral-800 dark:text-neutral-200"
            placeholder="e.g., 3.5rem"
          />
        </div>
        <div>
          <label for="banner-overlap-mobile" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
            Mobile Content Overlap
          </label>
          <input 
            type="text" 
            id="banner-overlap-mobile" 
            bind:value={bannerConfig.layout.overlap.mobile}
            on:input={handleChange}
            class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm text-neutral-800 dark:text-neutral-200"
            placeholder="e.g., 2rem"
          />
        </div>
      </div>
      
      <div>
        <label for="banner-max-width" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
          Maximum Width (px)
        </label>
        <input 
          type="number" 
          id="banner-max-width" 
          bind:value={bannerConfig.layout.maxWidth}
          on:input={handleChange}
          class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm text-neutral-800 dark:text-neutral-200"
          placeholder="e.g., 1920"
        />
      </div>
    </div>
  </div>
  
  <!-- Navbar Spacing Settings (for all banner types) -->
  <div class="space-y-4 pt-6 mt-6 border-t border-neutral-200 dark:border-neutral-700">
    <h4 class="text-md font-medium text-black/80 dark:text-white/80 mb-3">Navbar Spacing</h4>
    
    <div class="space-y-4">
      <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div>
          <label for="navbar-spacing-standard" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
            Standard Banner Spacing
          </label>
          <input 
            type="text" 
            id="navbar-spacing-standard" 
            bind:value={bannerConfig.navbarSpacing.standard}
            on:input={handleChange}
            class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm text-neutral-800 dark:text-neutral-200"
            placeholder="e.g., 0"
          />
          <p class="mt-1 text-xs text-neutral-500 dark:text-neutral-400">
            Space between navbar and standard banner
          </p>
        </div>
        <div>
          <label for="navbar-spacing-timeline" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
            Timeline Banner Spacing
          </label>
          <input 
            type="text" 
            id="navbar-spacing-timeline" 
            bind:value={bannerConfig.navbarSpacing.timeline}
            on:input={handleChange}
            class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm text-neutral-800 dark:text-neutral-200"
            placeholder="e.g., 4.5rem"
          />
          <p class="mt-1 text-xs text-neutral-500 dark:text-neutral-400">
            Space between navbar and timeline banner
          </p>
        </div>
      </div>
      
      <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div>
          <label for="navbar-spacing-video" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
            Video Banner Spacing
          </label>
          <input 
            type="text" 
            id="navbar-spacing-video" 
            bind:value={bannerConfig.navbarSpacing.video}
            on:input={handleChange}
            class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm text-neutral-800 dark:text-neutral-200"
            placeholder="e.g., 4.5rem"
          />
          <p class="mt-1 text-xs text-neutral-500 dark:text-neutral-400">
            Space between navbar and video banner
          </p>
        </div>
        <div>
          <label for="navbar-spacing-image" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
            Image Banner Spacing
          </label>
          <input 
            type="text" 
            id="navbar-spacing-image" 
            bind:value={bannerConfig.navbarSpacing.image}
            on:input={handleChange}
            class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm text-neutral-800 dark:text-neutral-200"
            placeholder="e.g., 4.5rem"
          />
          <p class="mt-1 text-xs text-neutral-500 dark:text-neutral-400">
            Space between navbar and image banner
          </p>
        </div>
      </div>
      
      <div class="p-3 bg-blue-50 dark:bg-blue-900/20 rounded-md text-sm text-blue-800 dark:text-blue-200">
        <p>These settings control the space between your navbar and different banner types. Increase values to add more space below the navbar.</p>
      </div>
    </div>
  </div>
</div>