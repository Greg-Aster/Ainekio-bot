<script>
    import { createEventDispatcher, onMount } from 'svelte';
    
    // Props
    export let navBarConfig;
    
    // Local state
    let editingLink = null;
    let showLinkEditor = false;
    let addingDropdownItem = false;
    let linkPresets = {};
    let reordering = false;
    
    // Variables for adding dropdown items
    let addDropdownName = '';
    let addDropdownUrl = '';
    let addDropdownExternal = false;
    
    // Event dispatcher
    const dispatch = createEventDispatcher();
    
    // Link presets (from your LinkPreset enum)
    onMount(() => {
      // In a real implementation, this would be imported from your config
      linkPresets = {
        0: { name: 'Home', url: '/' },
        1: { name: 'Archive', url: '/archive/' },
        2: { name: 'About', url: '/about/' },
        3: { name: 'Community', url: '/community/' },
        4: { name: 'Projects', url: '/projects/' },
        5: { name: 'Configs', url: '/configs/' },
        6: { name: 'Friends', url: '/friends/' },
        7: { name: 'New Post', url: '/new-post/' }
      };
    });
    
    // Function to add a new link
    function addNewLink() {
      editingLink = {
        isNew: true,
        data: {
          name: '',
          url: '',
          external: false,
          dropdown: []
        },
        isPreset: false,
        presetIndex: null
      };
      showLinkEditor = true;
    }
    
    // Function to edit a link
    function editLink(index) {
      const link = navBarConfig.links[index];
      
      if (typeof link === 'number') {
        // It's a preset
        editingLink = {
          isNew: false,
          index: index,
          data: { ...linkPresets[link] },
          isPreset: true,
          presetIndex: link
        };
      } else {
        // It's a custom link
        editingLink = {
          isNew: false,
          index: index,
          data: { ...link },
          isPreset: false,
          presetIndex: null
        };
      }
      
      showLinkEditor = true;
    }
    
    // Function to save link
    function saveLink(link) {
      if (link.isNew) {
        // Add new link
        if (link.isPreset) {
          navBarConfig.links = [...navBarConfig.links, link.presetIndex];
        } else {
          navBarConfig.links = [...navBarConfig.links, link.data];
        }
      } else {
        // Update existing link
        const newLinks = [...navBarConfig.links];
        if (link.isPreset) {
          newLinks[link.index] = link.presetIndex;
        } else {
          newLinks[link.index] = link.data;
        }
        navBarConfig.links = newLinks;
      }
      
      showLinkEditor = false;
      dispatch('change', navBarConfig);
    }
    
    // Function to delete a link
    function deleteLink(index) {
      const link = navBarConfig.links[index];
      const linkName = typeof link === 'number' ? linkPresets[link].name : link.name;
      
      if (confirm(`Are you sure you want to delete the "${linkName}" navigation link?`)) {
        navBarConfig.links = navBarConfig.links.filter((_, i) => i !== index);
        dispatch('change', navBarConfig);
      }
    }
    
    // Function to move a link up or down
    function moveLink(index, direction) {
      if ((direction === 'up' && index === 0) || 
          (direction === 'down' && index === navBarConfig.links.length - 1)) {
        return; // Can't move beyond the start or end
      }
      
      const newLinks = [...navBarConfig.links];
      const targetIndex = direction === 'up' ? index - 1 : index + 1;
      
      // Swap links
      [newLinks[index], newLinks[targetIndex]] = [newLinks[targetIndex], newLinks[index]];
      
      navBarConfig.links = newLinks;
      dispatch('change', navBarConfig);
    }
    
    // Helper function to get link name
    function getLinkName(link) {
      return typeof link === 'number' ? linkPresets[link]?.name || `Preset ${link}` : link.name;
    }
    
    // Helper function to get link URL
    function getLinkUrl(link) {
      return typeof link === 'number' ? linkPresets[link]?.url || '/' : link.url;
    }
    
    // Function to toggle a dropdown editor
    function toggleDropdownEditor(index) {
      addingDropdownItem = addingDropdownItem === index ? null : index;
      
      // Reset form values when showing the form
      if (addingDropdownItem !== null) {
        addDropdownName = '';
        addDropdownUrl = '';
        addDropdownExternal = false;
      }
    }
    
    // Function to add a dropdown item
    function addDropdownItem(index, item) {
      const link = navBarConfig.links[index];
      
      if (typeof link === 'number') {
        // Can't add dropdown to preset
        return;
      }
      
      if (!link.dropdown) {
        link.dropdown = [];
      }
      
      link.dropdown.push(item);
      addingDropdownItem = null;
      dispatch('change', navBarConfig);
    }
    
    // Function to remove a dropdown item
    function removeDropdownItem(linkIndex, itemIndex) {
      const link = navBarConfig.links[linkIndex];
      
      if (typeof link === 'number' || !link.dropdown) {
        return;
      }
      
      link.dropdown = link.dropdown.filter((_, i) => i !== itemIndex);
      dispatch('change', navBarConfig);
    }
  </script>
  
  <div class="navigation-config-tab">
    <div class="mb-6">
      <h2 class="text-xl font-semibold text-black/80 dark:text-white/80 mb-4">Navigation Menu</h2>
      <p class="text-neutral-600 dark:text-neutral-400 mb-4">
        Configure the navigation links that appear in your site's header. Add, edit, or remove links as needed.
      </p>
      
      <div class="flex justify-end mb-4">
        <button 
          class="py-1.5 px-3 bg-[var(--primary)] hover:opacity-90 text-white font-medium rounded-md transition-opacity text-sm flex items-center"
          on:click={addNewLink}
        >
          <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 mr-1" viewBox="0 0 20 20" fill="currentColor">
            <path fill-rule="evenodd" d="M10 5a1 1 0 011 1v3h3a1 1 0 110 2h-3v3a1 1 0 11-2 0v-3H6a1 1 0 110-2h3V6a1 1 0 011-1z" clip-rule="evenodd" />
          </svg>
          Add Link
        </button>
      </div>
    </div>
    
    <!-- Links List -->
    <div class="links-list space-y-3 mb-6">
      {#if !navBarConfig.links || navBarConfig.links.length === 0}
        <div class="bg-neutral-50 dark:bg-neutral-800/30 p-4 rounded-lg border border-neutral-200 dark:border-neutral-700 text-center">
          <p class="text-neutral-500 dark:text-neutral-400">No navigation links configured. Click "Add Link" to create one.</p>
        </div>
      {:else}
        {#each navBarConfig.links as link, index}
          <div class="link-item bg-neutral-50 dark:bg-neutral-800/50 rounded-lg border border-neutral-200 dark:border-neutral-700 overflow-hidden">
            <!-- Link Header -->
            <div class="p-4 flex justify-between items-start">
              <div>
                <h4 class="font-medium text-black/90 dark:text-white/90 flex items-center">
                    {#if typeof link === 'number'}
                    <span class="inline-block bg-blue-100 dark:bg-blue-900/30 text-blue-800 dark:text-blue-300 text-xs rounded px-2 py-0.5 mr-2">
                      Preset
                    </span>
                  {/if}
                  {getLinkName(link)}
                </h4>
                <div class="text-sm text-neutral-600 dark:text-neutral-400 mt-1">
                  URL: {getLinkUrl(link)}
                  {#if typeof link !== 'number' && link.external}
                  <span class="ml-2 text-xs bg-neutral-200 dark:bg-neutral-700 text-neutral-700 dark:text-neutral-300 rounded px-1.5 py-0.5">
                    External
                  </span>
                {/if}
                </div>
              </div>
              <div class="flex space-x-1">
                <button 
                  class="p-1.5 text-neutral-500 hover:text-neutral-700 dark:hover:text-neutral-300 rounded"
                  title="Move Up"
                  on:click={() => moveLink(index, 'up')}
                  disabled={index === 0}
                >
                  <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 15l7-7 7 7" />
                  </svg>
                </button>
                <button 
                  class="p-1.5 text-neutral-500 hover:text-neutral-700 dark:hover:text-neutral-300 rounded"
                  title="Move Down"
                  on:click={() => moveLink(index, 'down')}
                  disabled={index === navBarConfig.links.length - 1}
                >
                  <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
                  </svg>
                </button>
                <button 
                  class="p-1.5 text-neutral-500 hover:text-[var(--primary)] rounded"
                  title="Edit Link"
                  on:click={() => editLink(index)}
                >
                  <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                  </svg>
                </button>
                <button 
                  class="p-1.5 text-neutral-500 hover:text-red-500 rounded"
                  title="Delete Link"
                  on:click={() => deleteLink(index)}
                >
                  <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                  </svg>
                </button>
              </div>
            </div>
            
            <!-- Dropdown Items (if any) -->
            {#if typeof link !== 'number' && link.dropdown && link.dropdown.length > 0}
              <div class="border-t border-neutral-200 dark:border-neutral-700 p-4 pt-3">
                <h5 class="text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-2">Dropdown Items</h5>
                
                <div class="space-y-2">
                  {#each link.dropdown as item, itemIndex}
                    <div class="flex justify-between items-center bg-white dark:bg-neutral-700 p-2 rounded border border-neutral-200 dark:border-neutral-600">
                      <div>
                        <span class="text-sm">{item.name}</span>
                        <div class="text-xs text-neutral-500 dark:text-neutral-400">
                          {item.url}
                          {#if item.external}
                          <span class="ml-1 bg-neutral-200 dark:bg-neutral-600 text-neutral-700 dark:text-neutral-300 rounded px-1 py-0.5 text-[10px]">
                            External
                          </span>
                        {/if}
                        </div>
                      </div>
                      <button 
                        class="p-1 text-neutral-500 hover:text-red-500 rounded-full"
                        title="Remove Item"
                        on:click={() => removeDropdownItem(index, itemIndex)}
                      >
                        <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
                        </svg>
                      </button>
                    </div>
                  {/each}
                </div>
                
                <div class="mt-3">
                  <button 
                    class="py-1 px-2 bg-neutral-200 dark:bg-neutral-600 hover:bg-neutral-300 dark:hover:bg-neutral-500 text-neutral-700 dark:text-neutral-200 text-xs rounded transition-colors flex items-center"
                    on:click={() => toggleDropdownEditor(index)}
                  >
                    <svg xmlns="http://www.w3.org/2000/svg" class="h-3 w-3 mr-1" viewBox="0 0 20 20" fill="currentColor">
                      <path fill-rule="evenodd" d="M10 5a1 1 0 011 1v3h3a1 1 0 110 2h-3v3a1 1 0 11-2 0v-3H6a1 1 0 110-2h3V6a1 1 0 011-1z" clip-rule="evenodd" />
                    </svg>
                    Add Dropdown Item
                  </button>
                </div>
                
                <!-- Add Dropdown Item Form -->
                {#if addingDropdownItem === index}
                  <div class="mt-3 p-3 bg-neutral-100 dark:bg-neutral-700/60 rounded border border-neutral-200 dark:border-neutral-600">
                    <h6 class="text-xs font-medium mb-2">Add Dropdown Item</h6>
                    
                    <div class="space-y-2">
                      <div>
                        <label class="block text-xs text-neutral-600 dark:text-neutral-400 mb-1">Name</label>
                        <input 
                          type="text" 
                          id="dropdown-name" 
                          class="w-full px-2 py-1 text-sm bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md transition" 
                          bind:value={addDropdownName}
                        />
                      </div>
                      
                      <div>
                        <label class="block text-xs text-neutral-600 dark:text-neutral-400 mb-1">URL</label>
                        <input 
                          type="text" 
                          id="dropdown-url" 
                          class="w-full px-2 py-1 text-sm bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md transition" 
                          bind:value={addDropdownUrl}
                        />
                      </div>
                      
                      <div class="flex items-center">
                        <input 
                          type="checkbox" 
                          id="dropdown-external" 
                          class="h-3 w-3 text-[var(--primary)] border-neutral-300 dark:border-neutral-600 rounded" 
                          bind:checked={addDropdownExternal}
                        />
                        <label for="dropdown-external" class="ml-2 block text-xs text-neutral-600 dark:text-neutral-400">
                          External Link
                        </label>
                      </div>
                      
                      <div class="flex justify-end space-x-2 pt-1">
                        <button 
                          class="py-1 px-2 border border-neutral-300 dark:border-neutral-600 text-neutral-700 dark:text-neutral-300 text-xs rounded hover:bg-neutral-50 dark:hover:bg-neutral-600 transition-colors"
                          on:click={() => toggleDropdownEditor(null)}
                        >
                          Cancel
                        </button>
                        
                        <button 
                          class="py-1 px-2 bg-[var(--primary)] hover:opacity-90 text-white text-xs rounded transition-opacity"
                          on:click={() => addDropdownItem(index, {
                            name: addDropdownName,
                            url: addDropdownUrl,
                            external: addDropdownExternal
                          })}
                        >
                          Add
                        </button>
                      </div>
                    </div>
                  </div>
                {/if}
              </div>
            {:else if typeof link !== 'number'}
              <div class="border-t border-neutral-200 dark:border-neutral-700 p-3 flex justify-center">
                <button 
                  class="py-1 px-2 bg-neutral-200 dark:bg-neutral-600 hover:bg-neutral-300 dark:hover:bg-neutral-500 text-neutral-700 dark:text-neutral-200 text-xs rounded transition-colors flex items-center"
                  on:click={() => toggleDropdownEditor(index)}
                >
                  <svg xmlns="http://www.w3.org/2000/svg" class="h-3 w-3 mr-1" viewBox="0 0 20 20" fill="currentColor">
                    <path fill-rule="evenodd" d="M10 5a1 1 0 011 1v3h3a1 1 0 110 2h-3v3a1 1 0 11-2 0v-3H6a1 1 0 110-2h3V6a1 1 0 011-1z" clip-rule="evenodd" />
                  </svg>
                  Add Dropdown
                </button>
              </div>
            {/if}
          </div>
        {/each}
      {/if}
    </div>
    
    <!-- Link Editor Modal -->
    {#if showLinkEditor}
      <div class="fixed inset-0 bg-black/50 dark:bg-black/60 z-50 flex items-center justify-center">
        <div class="bg-white dark:bg-neutral-800 rounded-lg max-w-lg w-full overflow-auto shadow-lg">
          <div class="p-5">
            <h3 class="text-xl font-semibold text-black/80 dark:text-white/80 mb-4">
              {editingLink.isNew ? 'Add Navigation Link' : 'Edit Navigation Link'}
            </h3>
            
            <!-- Link Type Selector -->
            <div class="mb-4">
              <label class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-2">Link Type</label>
              <div class="flex space-x-4">
                <label class="flex items-center">
                  <input 
                    type="radio" 
                    name="link-type" 
                    value="preset" 
                    checked={editingLink.isPreset}
                    on:change={() => { editingLink.isPreset = true; }}
                    class="h-4 w-4 text-[var(--primary)] border-neutral-300 dark:border-neutral-600" 
                  />
                  <span class="ml-2 text-sm text-neutral-700 dark:text-neutral-300">Preset Link</span>
                </label>
                
                <label class="flex items-center">
                  <input 
                    type="radio" 
                    name="link-type" 
                    value="custom" 
                    checked={!editingLink.isPreset}
                    on:change={() => { editingLink.isPreset = false; }}
                    class="h-4 w-4 text-[var(--primary)] border-neutral-300 dark:border-neutral-600" 
                  />
                  <span class="ml-2 text-sm text-neutral-700 dark:text-neutral-300">Custom Link</span>
                </label>
              </div>
            </div>
            
            {#if editingLink.isPreset}
              <!-- Preset Selector -->
              <div class="mb-4">
                <label for="preset-select" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
                  Select Preset
                </label>
                <select 
                  id="preset-select" 
                  bind:value={editingLink.presetIndex}
                  class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-l text-sm text-neutral-900 dark:text-neutral-100"
                >
                  <option value={null} disabled>Select a preset...</option>
                  {#each Object.entries(linkPresets) as [index, preset]}
                    <option value={parseInt(index)}>{preset.name} ({preset.url})</option>
                  {/each}
                </select>
              </div>
            {:else}
              <!-- Custom Link Form -->
              <div class="space-y-4">
                <div>
                  <label for="link-name" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
                    Link Name
                  </label>
                  <input 
                    type="text" 
                    id="link-name" 
                    bind:value={editingLink.data.name}
                    class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-l text-sm text-neutral-900 dark:text-neutral-100" 
                    placeholder="e.g. Projects"
                  />
                </div>
                
                <div>
                  <label for="link-url" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
                    URL
                  </label>
                  <input 
                    type="text" 
                    id="link-url" 
                    bind:value={editingLink.data.url}
                    class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-l text-sm text-neutral-900 dark:text-neutral-100" 
                    placeholder="e.g. /projects/ or https://example.com"
                  />
                </div>
                
                <div class="flex items-center">
                  <input 
                    type="checkbox" 
                    id="link-external" 
                    bind:checked={editingLink.data.external}
                    class="h-4 w-4 text-[var(--primary)] border-neutral-300 dark:border-neutral-600 rounded" 
                  />
                  <label for="link-external" class="ml-2 block text-sm text-neutral-700 dark:text-neutral-300">
                    External Link
                  </label>
                </div>
              </div>
            {/if}
            
            <div class="flex justify-end space-x-3 mt-6 pt-4 border-t border-neutral-200 dark:border-neutral-700">
              <button 
                type="button"
                class="px-4 py-2 border border-neutral-300 dark:border-neutral-600 text-neutral-700 dark:text-neutral-300 rounded-md hover:bg-neutral-50 dark:hover:bg-neutral-700 transition-colors"
                on:click={() => showLinkEditor = false}
              >
                Cancel
              </button>
              
              <button 
                type="button"
                class="px-4 py-2 bg-[var(--primary)] hover:opacity-90 text-white font-medium rounded-md transition-opacity"
                on:click={() => saveLink(editingLink)}
                disabled={editingLink.isPreset && editingLink.presetIndex === null}
              >
                {editingLink.isNew ? 'Add Link' : 'Save Changes'}
              </button>
            </div>
          </div>
        </div>
      </div>
    {/if}
  </div>