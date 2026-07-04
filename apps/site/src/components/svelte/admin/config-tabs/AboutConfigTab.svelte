<script lang="ts">
  import { onMount, createEventDispatcher } from 'svelte';
  import type { AboutConfig } from '../types/aboutconfig';
  
  // Props
  export let aboutConfig: AboutConfig;
  
  // Event dispatcher to notify parent of changes
  const dispatch = createEventDispatcher();
  
  // Local state
  let activeSection = 'team';
  
  // Sections for tab navigation
  const sections = [
    { id: 'team', label: 'Team Section' },
    { id: 'content', label: 'Content Section' },
    { id: 'contact', label: 'Contact Section' }
  ];
  
  // Function to notify parent of changes
  function notifyChanges() {
    dispatch('change');
  }
  
  // Function to toggle a section's enabled status
  function toggleSection(section: keyof AboutConfig) {
    aboutConfig[section].enabled = !aboutConfig[section].enabled;
    notifyChanges();
  }
  
  // Function to update display order for contact section
  function updateDisplayOrder() {
    notifyChanges();
  }
  
  // Function to move item up in display order
  function moveUp(index: number) {
    if (index > 0) {
      const temp = aboutConfig.contact.displayOrder[index];
      aboutConfig.contact.displayOrder[index] = aboutConfig.contact.displayOrder[index - 1];
      aboutConfig.contact.displayOrder[index - 1] = temp;
      notifyChanges();
    }
  }
  
  // Function to move item down in display order
  function moveDown(index: number) {
    if (index < aboutConfig.contact.displayOrder.length - 1) {
      const temp = aboutConfig.contact.displayOrder[index];
      aboutConfig.contact.displayOrder[index] = aboutConfig.contact.displayOrder[index + 1];
      aboutConfig.contact.displayOrder[index + 1] = temp;
      notifyChanges();
    }
  }
  
  // Display names for order items
  const displayNames = {
    'description': 'Description Text',
    'email': 'Email Address',
    'phone': 'Phone Number',
    'address': 'Physical Address',
    'hours': 'Office Hours'
  };
</script>

<div class="about-config-tab">
  <div class="mb-6">
    <h2 class="text-xl font-semibold text-black/80 dark:text-white/80 mb-4">About Page Configuration</h2>
    <p class="text-neutral-600 dark:text-neutral-400 mb-4">
      Configure your about page sections, layout, and content.
    </p>
    
    <!-- Section Tabs -->
    <div class="flex flex-wrap mb-6 space-x-2 md:space-x-4 border-b border-neutral-200 dark:border-neutral-700">
      {#each sections as section}
        <button 
          class="py-2 px-3 md:px-4 text-sm md:text-base {activeSection === section.id ? 'text-[var(--primary)] border-b-2 border-[var(--primary)]' : 'text-neutral-600 dark:text-neutral-400'}"
          on:click={() => activeSection = section.id}
        >
          {section.label}
        </button>
      {/each}
    </div>
    
    <!-- Team Section Configuration -->
    {#if activeSection === 'team'}
      <div class="team-section space-y-6">
        <div class="card bg-white dark:bg-neutral-800 p-5 rounded-lg border border-neutral-200 dark:border-neutral-700">
          <div class="flex justify-between items-center mb-4">
            <h3 class="font-medium text-lg text-black/80 dark:text-white/80 text-black/80 dark:text-white/80">Team Section</h3>
            <label class="flex items-center">
              <input 
                type="checkbox" 
                bind:checked={aboutConfig.team.enabled} 
                on:change={notifyChanges}
                class="mr-2 h-4 w-4"
              />
              <span class="text-sm font-medium text-neutral-700 dark:text-neutral-300">Enabled</span>
            </label>
          </div>
          
          <div class="mb-4">
            <label class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
              Section Title
            </label>
            <input 
              type="text" 
              bind:value={aboutConfig.team.title} 
              on:input={notifyChanges}
                class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm text-neutral-800 dark:text-neutral-200"
            />
          </div>
          
          <div class="mb-4">
            <label class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
              Description
            </label>
            <textarea 
              bind:value={aboutConfig.team.description} 
              on:input={notifyChanges}
              rows="2" 
                class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm text-neutral-800 dark:text-neutral-200"
            ></textarea>
          </div>
          
          <div class="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
            <div>
              <label class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
                Layout Style
              </label>
              <select 
                bind:value={aboutConfig.team.layout} 
                on:change={notifyChanges}
                  class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm text-neutral-800 dark:text-neutral-200"
              >
                <option value="grid">Grid Layout</option>
                <option value="list">List Layout</option>
                <option value="cards">Card Layout</option>
              </select>
            </div>
            
            <div>
              <label class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
                Avatar Shape
              </label>
              <select 
                bind:value={aboutConfig.team.avatarShape} 
                on:change={notifyChanges}
                  class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm text-neutral-800 dark:text-neutral-200"
              >
                <option value="square">Square</option>
                <option value="rounded">Rounded</option>
                <option value="circle">Circle</option>
              </select>
            </div>
          </div>
          
          <div class="mb-4">
            <label class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
              Columns
            </label>
            <div class="grid grid-cols-3 gap-4">
              <div>
                <label class="block text-xs font-medium text-neutral-500 dark:text-neutral-400 mb-1">
                  Mobile
                </label>
                <input 
                  type="number" 
                  min="1" 
                  max="2" 
                  bind:value={aboutConfig.team.columns.mobile} 
                  on:input={notifyChanges}
                    class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm text-neutral-800 dark:text-neutral-200"
                />
              </div>
              <div>
                <label class="block text-xs font-medium text-neutral-500 dark:text-neutral-400 mb-1">
                  Tablet
                </label>
                <input 
                  type="number" 
                  min="1" 
                  max="3" 
                  bind:value={aboutConfig.team.columns.tablet} 
                  on:input={notifyChanges}
                    class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm text-neutral-800 dark:text-neutral-200"
                />
              </div>
              <div>
                <label class="block text-xs font-medium text-neutral-500 dark:text-neutral-400 mb-1">
                  Desktop
                </label>
                <input 
                  type="number" 
                  min="1" 
                  max="4" 
                  bind:value={aboutConfig.team.columns.desktop} 
                  on:input={notifyChanges}
                    class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm text-neutral-800 dark:text-neutral-200"
                />
              </div>
            </div>
          </div>
          
          <div class="flex flex-col sm:flex-row gap-4">
            <label class="flex items-center text-sm font-medium text-neutral-700 dark:text-neutral-300">
              <input 
                type="checkbox" 
                bind:checked={aboutConfig.team.showEmail} 
                on:change={notifyChanges}
                class="mr-2 h-4 w-4"
              />
              Show Email Addresses
            </label>
            
            <label class="flex items-center text-sm font-medium text-neutral-700 dark:text-neutral-300">
              <input 
                type="checkbox" 
                bind:checked={aboutConfig.team.showRole} 
                on:change={notifyChanges}
                class="mr-2 h-4 w-4"
              />
              Show Team Member Roles
            </label>
          </div>
        </div>
      </div>
    
    <!-- Content Section Configuration -->
    {:else if activeSection === 'content'}
      <div class="content-section space-y-6">
        <div class="card bg-white dark:bg-neutral-800 p-5 rounded-lg border border-neutral-200 dark:border-neutral-700">
          <div class="flex justify-between items-center mb-4">
            <h3 class="font-medium text-lg text-black/80 dark:text-white/80">Content Section</h3>
            <label class="flex items-center">
              <input 
                type="checkbox" 
                bind:checked={aboutConfig.content.enabled} 
                on:change={notifyChanges}
                class="mr-2 h-4 w-4"
              />
              <span class="text-sm font-medium text-neutral-700 dark:text-neutral-300">Enabled</span>
            </label>
          </div>
          
          <div class="mb-4">
            <label class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
              Default Title
            </label>
            <input 
              type="text" 
              bind:value={aboutConfig.content.defaultTitle} 
              on:input={notifyChanges}
                class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm text-neutral-800 dark:text-neutral-200"
            />
            <p class="text-xs text-neutral-500 mt-1">This title is shown when no team member is selected</p>
          </div>
          
          <div class="mb-4">
            <label class="flex items-center text-sm font-medium text-neutral-700 dark:text-neutral-300">
              <input 
                type="checkbox" 
                bind:checked={aboutConfig.content.showTableOfContents} 
                on:change={notifyChanges}
                class="mr-2 h-4 w-4"
              />
              Show Table of Contents
            </label>
            <p class="text-xs text-neutral-500 mt-1 ml-6">Display a table of contents for the about page content</p>
          </div>
          
          <div class="bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800/30 rounded-md p-3 text-amber-800 dark:text-amber-200 text-sm mt-6">
            <div class="flex">
              <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 mr-2 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
              </svg>
              <div>
                <p class="font-medium">Note about Content</p>
                <p class="mt-1">The actual content is pulled from your markdown files in the content folder. This configuration only controls how the content is displayed.</p>
              </div>
            </div>
          </div>
        </div>
      </div>
    
    <!-- Contact Section Configuration -->
    {:else if activeSection === 'contact'}
      <div class="contact-section space-y-6">
        <div class="card bg-white dark:bg-neutral-800 p-5 rounded-lg border border-neutral-200 dark:border-neutral-700">
          <div class="flex justify-between items-center mb-4">
            <h3 class="font-medium text-lg text-black/80 dark:text-white/80">Contact Section</h3>
            <label class="flex items-center">
              <input 
                type="checkbox" 
                bind:checked={aboutConfig.contact.enabled} 
                on:change={notifyChanges}
                class="mr-2 h-4 w-4"
              />
              <span class="text-sm font-medium text-neutral-700 dark:text-neutral-300">Enabled</span>
            </label>
          </div>
          
          <div class="mb-4">
            <label class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
              Section Title
            </label>
            <input 
              type="text" 
              bind:value={aboutConfig.contact.title} 
              on:input={notifyChanges}
                class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm text-neutral-800 dark:text-neutral-200"
            />
          </div>
          
          <div class="mb-4">
            <label class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
              Description
            </label>
            <textarea 
              bind:value={aboutConfig.contact.description} 
              on:input={notifyChanges}
              rows="3" 
                class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm text-neutral-800 dark:text-neutral-200"
            ></textarea>
          </div>
          
          <h4 class="font-medium text-base mb-3 mt-6 text-neutral-800 dark:text-neutral-200">

Contact Information</h4>
          
          <!-- Email Input -->
          <div class="mb-4">
            <label class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
              Email Address
            </label>
            <input 
              type="email" 
              bind:value={aboutConfig.contact.contactInfo.email} 
              on:input={notifyChanges}
                class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm text-neutral-800 dark:text-neutral-200"
            />
          </div>
          
          <!-- Phone Input (Optional) -->
          <div class="mb-4">
            <label class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
              Phone Number (Optional)
            </label>
            <input 
              type="text" 
              bind:value={aboutConfig.contact.contactInfo.phone} 
              on:input={notifyChanges}
                class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm text-neutral-800 dark:text-neutral-200"
            />
          </div>
          
          <!-- Address Input (Optional) -->
          <div class="mb-4">
            <label class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
              Address (Optional)
            </label>
            <textarea 
              bind:value={aboutConfig.contact.contactInfo.address} 
              on:input={notifyChanges}
              rows="2" 
                class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm text-neutral-800 dark:text-neutral-200"
            ></textarea>
          </div>
          
          <!-- Hours Input (Optional) -->
          <div class="mb-4">
            <label class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
              Hours (Optional)
            </label>
            <input 
              type="text" 
              bind:value={aboutConfig.contact.contactInfo.hours} 
              on:input={notifyChanges}
              placeholder="e.g., Mon-Fri: 9am-5pm" 
                class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm text-neutral-800 dark:text-neutral-200"
            />
          </div>
          
          <h4 class="font-medium text-base mb-3 mt-6 text-neutral-800 dark:text-neutral-200">

Display Order</h4>
          <p class="text-sm text-neutral-500 dark:text-neutral-400 mb-3">
            Drag and drop to change the order of contact information displayed on the page.
          </p>
          
          <div class="space-y-2 mb-4">
            {#each aboutConfig.contact.displayOrder as item, index}
              {#if item === 'description' || (item === 'email' && aboutConfig.contact.contactInfo.email) || 
                  (item === 'phone' && aboutConfig.contact.contactInfo.phone) || 
                  (item === 'address' && aboutConfig.contact.contactInfo.address) || 
                  (item === 'hours' && aboutConfig.contact.contactInfo.hours)}
                <div class="flex items-center justify-between p-3 bg-neutral-50 dark:bg-neutral-800/50 rounded-md border border-neutral-200 dark:border-neutral-700">
                  <span class="text-sm font-medium text-neutral-700 dark:text-neutral-300">
                    {displayNames[item] || item}
                  </span>
                  <div class="flex space-x-1">
                    <button 
                      class="p-1 text-neutral-500 hover:text-neutral-700 dark:hover:text-neutral-300 disabled:opacity-30"
                      on:click={() => moveUp(index)}
                      disabled={index === 0}
                    >
                      <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 15l7-7 7 7" />
                      </svg>
                    </button>
                    <button 
                      class="p-1 text-neutral-500 hover:text-neutral-700 dark:hover:text-neutral-300 disabled:opacity-30"
                      on:click={() => moveDown(index)}
                      disabled={index === aboutConfig.contact.displayOrder.length - 1}
                    >
                      <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
                      </svg>
                    </button>
                  </div>
                </div>
              {/if}
            {/each}
          </div>
          
          <!-- Info about missing items -->
          {#if aboutConfig.contact.displayOrder.length === 0}
            <p class="text-sm text-amber-500 dark:text-amber-400">
              No display items selected. Add items to the display order list to show them on the page.
            </p>
          {/if}
          
          <!-- Add item to display order if missing -->
          <div class="mt-4">
            <label class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
              Add Item to Display
            </label>
            <div class="flex space-x-2">
              <select 
                id="add-display-item" 
                class="flex-1 px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm"
              >
                {#each ['description', 'email', 'phone', 'address', 'hours'] as item}
                  {#if !aboutConfig.contact.displayOrder.includes(item)}
                    <option value={item}>{displayNames[item]}</option>
                  {/if}
                {/each}
              </select>
              <button 
                class="px-3 py-2 bg-[var(--primary)] hover:opacity-90 text-white font-medium rounded-md transition-opacity text-sm"
                on:click={() => {
                  const select = document.getElementById('add-display-item') as HTMLSelectElement;
                  if (select && select.value && !aboutConfig.contact.displayOrder.includes(select.value)) {
                    aboutConfig.contact.displayOrder = [...aboutConfig.contact.displayOrder, select.value];
                    notifyChanges();
                  }
                }}
              >
                Add
              </button>
            </div>
          </div>
        </div>
        
        <!-- Match Original Layout Helper -->
        <div class="mt-4 p-4 bg-neutral-50 dark:bg-neutral-800 rounded-lg border border-neutral-200 dark:border-neutral-700">
          <h4 class="font-medium text-base mb-3">Match Original Layout</h4>
          <p class="text-sm text-neutral-500 dark:text-neutral-400 mb-3">
            This will set the configuration to exactly match the original about.astro layout.
          </p>
          <button 
            class="px-3 py-2 bg-amber-500 hover:bg-amber-600 text-white font-medium rounded-md transition-colors text-sm"
            on:click={() => {
              // Set configuration to match original about.astro layout
              aboutConfig.team.enabled = true;
              aboutConfig.team.title = "Our Team";
              aboutConfig.team.description = "";
              aboutConfig.team.layout = "grid";
              aboutConfig.team.columns = { mobile: 1, tablet: 2, desktop: 3 };
              aboutConfig.team.showEmail = true;
              aboutConfig.team.showRole = true;
              aboutConfig.team.avatarShape = "rounded";
              
              aboutConfig.content.enabled = true;
              aboutConfig.content.defaultTitle = "About The Project";
              aboutConfig.content.showTableOfContents = true;
              
              aboutConfig.contact.enabled = true;
              aboutConfig.contact.title = "Get In Touch";
              aboutConfig.contact.description = "Have questions, ideas, or want to collaborate? We'd love to hear from you! Please Email";
              aboutConfig.contact.contactInfo.email = "Greg@dndiy.org";
              aboutConfig.contact.displayOrder = ["description", "email"];
              
              notifyChanges();
            }}
          >
            Apply Original Layout
          </button>
        </div>
      </div>
    {/if}
  </div>
</div>