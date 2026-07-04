<script>
  import { createEventDispatcher } from 'svelte';
  
  // Props
  export let siteConfig;
  
  // Local state
  let editingFavicon = null;
  let showFaviconEditor = false;
  let uploadingFavicon = false;
  
  // Event dispatcher
  const dispatch = createEventDispatcher();
  
  // Function to add a favicon
  function addFavicon() {
    editingFavicon = {
      isNew: true,
      data: {
        src: '',
        theme: 'light',
        sizes: ''
      }
    };
    showFaviconEditor = true;
  }
  
  // Function to edit a favicon
  function editFavicon(index) {
    editingFavicon = {
      isNew: false,
      index: index,
      data: { ...siteConfig.favicon[index] }
    };
    showFaviconEditor = true;
  }
  
  // Function to save favicon
  function saveFavicon() {
    if (editingFavicon.isNew) {
      // Add new favicon
      if (!siteConfig.favicon) {
        siteConfig.favicon = [];
      }
      siteConfig.favicon = [...siteConfig.favicon, editingFavicon.data];
    } else {
      // Update existing favicon
      const newFavicons = [...siteConfig.favicon];
      newFavicons[editingFavicon.index] = editingFavicon.data;
      siteConfig.favicon = newFavicons;
    }
    
    showFaviconEditor = false;
    dispatch('change', siteConfig);
  }
  
  // Function to delete favicon
  function deleteFavicon(index) {
    if (confirm('Are you sure you want to delete this favicon?')) {
      siteConfig.favicon = siteConfig.favicon.filter((_, i) => i !== index);
      dispatch('change', siteConfig);
    }
  }
  
  // Function to handle favicon upload
  function handleFaviconUpload() {
    // In a real implementation, this would upload to a server
    // For demo purposes, we'll simulate a delay
    uploadingFavicon = true;
    
    setTimeout(() => {
      // Set a demo favicon URL
      editingFavicon.data.src = '/api/placeholder/32/32';
      uploadingFavicon = false;
    }, 1500);
  }
</script>

<!-- Favicon Settings -->
<div class="bg-neutral-50 dark:bg-neutral-800/50 p-5 rounded-lg border border-neutral-200 dark:border-neutral-700">
  <div class="flex justify-between items-start mb-4">
    <div>
      <h3 class="text-lg font-medium text-black/80 dark:text-white/80">Favicon</h3>
      <p class="text-sm text-neutral-500 dark:text-neutral-400 mt-1">
        The small icon shown in browser tabs and bookmarks
      </p>
    </div>
    <button 
      class="py-1.5 px-3 bg-[var(--primary)] hover:opacity-90 text-white font-medium rounded-md transition-opacity text-sm flex items-center"
      on:click={addFavicon}
    >
      <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 mr-1" viewBox="0 0 20 20" fill="currentColor">
        <path fill-rule="evenodd" d="M10 5a1 1 0 011 1v3h3a1 1 0 110 2h-3v3a1 1 0 11-2 0v-3H6a1 1 0 110-2h3V6a1 1 0 011-1z" clip-rule="evenodd" />
      </svg>
      Add Favicon
    </button>
  </div>
  
  <div class="favicons-grid flex flex-wrap gap-3 mb-4">
    {#if !siteConfig.favicon || siteConfig.favicon.length === 0}
      <div class="w-full bg-neutral-100 dark:bg-neutral-700/30 p-4 rounded-lg border border-neutral-200 dark:border-neutral-700 text-center">
        <p class="text-neutral-500 dark:text-neutral-400">No custom favicons configured. Using default favicon.</p>
      </div>
    {:else}
      {#each siteConfig.favicon as favicon, index}
        <div class="favicon-item relative bg-white dark:bg-neutral-700 p-3 rounded-lg border border-neutral-200 dark:border-neutral-600 hover:border-[var(--primary)] transition-colors">
          <div class="w-16 h-16 flex items-center justify-center">
            <img src={favicon.src} alt="Favicon" class="max-w-full max-h-full" />
          </div>
          
          <div class="mt-2 text-center">
            <div class="text-xs font-medium text-neutral-900 dark:text-neutral-100">
              {favicon.sizes || 'Default'}
            </div>
            <div class="text-xs text-neutral-500 dark:text-neutral-400">
              {favicon.theme || 'All themes'}
            </div>
          </div>
          
          <div class="absolute top-1 right-1 flex space-x-1">
            <button 
              class="text-neutral-400 hover:text-[var(--primary)] bg-white dark:bg-neutral-700 rounded-full p-1 w-6 h-6 flex items-center justify-center shadow-sm"
              title="Edit Favicon"
              on:click={() => editFavicon(index)}
            >
              <svg xmlns="http://www.w3.org/2000/svg" class="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
              </svg>
            </button>
            <button 
              class="text-neutral-400 hover:text-red-500 bg-white dark:bg-neutral-700 rounded-full p-1 w-6 h-6 flex items-center justify-center shadow-sm"
              title="Delete Favicon"
              on:click={() => deleteFavicon(index)}
            >
              <svg xmlns="http://www.w3.org/2000/svg" class="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
              </svg>
            </button>
          </div>
        </div>
      {/each}
    {/if}
  </div>
  
  <div class="text-sm bg-neutral-100 dark:bg-neutral-700/30 p-3 rounded-lg border border-neutral-200 dark:border-neutral-700 mb-2">
    <h4 class="font-medium text-black/80 dark:text-white/80 flex items-center">
      <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 mr-1" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
      </svg>
      Tips for favicons:
    </h4>
    <ul class="mt-2 space-y-1 list-disc pl-5 text-neutral-600 dark:text-neutral-400 text-xs">
      <li>Create square images (recommended sizes: 16x16, 32x32, 180x180)</li>
      <li>Use PNG format for best compatibility</li>
      <li>You can add different favicons for light and dark themes</li>
      <li>If no favicons are added, the default site favicon will be used</li>
    </ul>
  </div>
</div>

{#if showFaviconEditor}
  <div class="fixed inset-0 bg-black/50 dark:bg-black/60 z-50 flex items-center justify-center">
    <div class="bg-white dark:bg-neutral-800 rounded-lg max-w-lg w-full overflow-auto shadow-lg">
      <div class="p-5">
        <h3 class="text-xl font-semibold text-black/80 dark:text-white/80 mb-4">
          {editingFavicon.isNew ? 'Add Favicon' : 'Edit Favicon'}
        </h3>
        
        <div class="space-y-4">
          <div>
            <label class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
              Favicon Image
            </label>
            <div class="flex items-center space-x-3">
              <div class="w-16 h-16 bg-neutral-100 dark:bg-neutral-700 border border-neutral-200 dark:border-neutral-600 rounded flex items-center justify-center overflow-hidden">
                {#if editingFavicon.data.src}
                  <img src={editingFavicon.data.src} alt="Favicon Preview" class="max-w-full max-h-full" />
                {:else}
                  <svg xmlns="http://www.w3.org/2000/svg" class="h-8 w-8 text-neutral-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
                  </svg>
                {/if}
              </div>
              
              <div class="flex-1">
                <button 
                  class="w-full py-2 px-3 bg-neutral-100 dark:bg-neutral-700 hover:bg-neutral-200 dark:hover:bg-neutral-600 text-neutral-700 dark:text-neutral-300 rounded text-sm transition-colors flex items-center justify-center"
                  on:click={handleFaviconUpload}
                  disabled={uploadingFavicon}
                >
                  {#if uploadingFavicon}
                    <svg class="animate-spin mr-2 h-4 w-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                      <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                      <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                    </svg>
                    Uploading...
                  {:else}
                    <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 mr-1" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
                    </svg>
                    Upload Image
                  {/if}
                </button>
              </div>
            </div>
          </div>
          
          <div>
            <label for="favicon-src" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
              Favicon Path
            </label>
            <input 
              type="text" 
              id="favicon-src" 
              bind:value={editingFavicon.data.src}
              class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-l text-sm text-neutral-900 dark:text-neutral-100" 
              placeholder="/favicon/icon-32x32.png"
            />
            <p class="mt-1 text-xs text-neutral-500 dark:text-neutral-400">
              Path to the favicon, relative to the /public directory
            </p>
          </div>
          
          <div class="grid grid-cols-2 gap-4">
            <div>
              <label for="favicon-theme" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
                Theme
              </label>
              <select 
                id="favicon-theme" 
                bind:value={editingFavicon.data.theme}
                class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-l text-sm text-neutral-900 dark:text-neutral-100"
              >
                <option value="">All Themes</option>
                <option value="light">Light Mode Only</option>
                <option value="dark">Dark Mode Only</option>
              </select>
            </div>
            
            <div>
              <label for="favicon-sizes" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
                Size
              </label>
              <input 
                type="text" 
                id="favicon-sizes" 
                bind:value={editingFavicon.data.sizes}
                class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-l text-sm text-neutral-900 dark:text-neutral-100" 
                placeholder="e.g. 32x32"
              />
            </div>
          </div>
        </div>
        
        <div class="flex justify-end space-x-3 mt-6 pt-4 border-t border-neutral-200 dark:border-neutral-700">
          <button 
            type="button"
            class="px-4 py-2 border border-neutral-300 dark:border-neutral-600 text-neutral-700 dark:text-neutral-300 rounded-md hover:bg-neutral-50 dark:hover:bg-neutral-700 transition-colors"
            on:click={() => showFaviconEditor = false}
          >
            Cancel
          </button>
          
          <button 
            type="button"
            class="px-4 py-2 bg-[var(--primary)] hover:opacity-90 text-white font-medium rounded-md transition-opacity"
            on:click={saveFavicon}
            disabled={!editingFavicon.data.src}
          >
            {editingFavicon.isNew ? 'Add Favicon' : 'Save Changes'}
          </button>
        </div>
      </div>
    </div>
  </div>
{/if}