<script lang="ts">
  import { createEventDispatcher } from 'svelte';
  import type { TimelineConfig } from '../types/timelineconfig';
  
  // Props
  export let timelineConfig: TimelineConfig;
  
  // Event dispatcher to notify parent of changes
  const dispatch = createEventDispatcher();
  
  // Local state
  let activeSection = 'general';
  let editingEra: any = null;
  let showEraEditor = false;
  
  // Sections for tab navigation
  const sections = [
    { id: 'general', label: 'General Settings' },
    { id: 'eras', label: 'Timeline Eras' },
    { id: 'display', label: 'Display Options' }
  ];
  
  // Function to notify parent of changes
  function notifyChanges() {
    dispatch('change');
  }
  
  // Function to add a new era
  function addEra() {
    editingEra = {
      isNew: true,
      data: {
        name: '',
        startYear: 2000,
        endYear: 2020,
        color: '#3b82f6',
        description: ''
      }
    };
    showEraEditor = true;
  }
  
  // Function to edit an era
  function editEra(index: number) {
    editingEra = {
      isNew: false,
      index: index,
      data: { ...timelineConfig.eras[index] }
    };
    showEraEditor = true;
  }
  
  // Function to save era
  function saveEra() {
    if (editingEra.isNew) {
      // Add new era
      timelineConfig.eras = [...timelineConfig.eras, editingEra.data];
    } else {
      // Update existing era
      const newEras = [...timelineConfig.eras];
      newEras[editingEra.index] = editingEra.data;
      timelineConfig.eras = newEras;
    }
    
    showEraEditor = false;
    notifyChanges();
  }
  
  // Function to delete era
  function deleteEra(index: number) {
    if (confirm('Are you sure you want to delete this era?')) {
      timelineConfig.eras = timelineConfig.eras.filter((_, i) => i !== index);
      notifyChanges();
    }
  }
  
  // Function to move era up in the list
  function moveEraUp(index: number) {
    if (index > 0) {
      const newEras = [...timelineConfig.eras];
      const temp = newEras[index];
      newEras[index] = newEras[index - 1];
      newEras[index - 1] = temp;
      timelineConfig.eras = newEras;
      notifyChanges();
    }
  }
  
  // Function to move era down in the list
  function moveEraDown(index: number) {
    if (index < timelineConfig.eras.length - 1) {
      const newEras = [...timelineConfig.eras];
      const temp = newEras[index];
      newEras[index] = newEras[index + 1];
      newEras[index + 1] = temp;
      timelineConfig.eras = newEras;
      notifyChanges();
    }
  }

  // Function to restore default configuration
  function restoreDefaults() {
    if (confirm('Are you sure you want to restore default configuration? This will reset all timeline settings.')) {
      // Reset to default configuration
      timelineConfig = {
        enableTimeline: true,
        defaultEra: 'present',
        showEraDescriptions: true,
        eras: [
          {
            name: 'past',
            startYear: 1900,
            endYear: 2000,
            color: '#6b7280', // gray-500
            description: 'Historical content and background'
          },
          {
            name: 'present',
            startYear: 2000,
            endYear: 2030,
            color: '#3b82f6', // blue-500
            description: 'Current projects and ongoing work'
          },
          {
            name: 'future',
            startYear: 2030,
            endYear: 2100,
            color: '#10b981', // emerald-500
            description: 'Planned projects and future vision'
          }
        ],
        displayOptions: {
          showYearLabels: true,
          showEraLabels: true,
          highlightCurrentYear: true,
          currentYear: new Date().getFullYear(),
          yearSpacing: 10,
          timelineHeight: 8
        }
      };
      
      notifyChanges();
    }
  }
</script>

<div class="timeline-config-tab">
  <div class="mb-6">
    <h2 class="text-xl font-semibold text-black/80 dark:text-white/80 mb-4">Timeline Configuration</h2>
    <p class="text-neutral-600 dark:text-neutral-400 mb-4">
      Configure the timeline component and define eras for your content.
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
    
    <!-- General Settings Tab -->
    {#if activeSection === 'general'}
      <div class="general-section space-y-6">
        <div class="card bg-white dark:bg-neutral-800 p-5 rounded-lg border border-neutral-200 dark:border-neutral-700">
          <div class="flex justify-between items-center mb-4">
            <h3 class="font-medium text-lg text-black/80 dark:text-white/80 text-black/80 dark:text-white/80">Timeline Settings</h3>
            <label class="flex items-center">
              <input 
                type="checkbox" 
                bind:checked={timelineConfig.enableTimeline} 
                on:change={notifyChanges}
                class="mr-2 h-4 w-4"
              />
              <span class="text-sm font-medium text-neutral-700 dark:text-neutral-300">Enable Timeline</span>
            </label>
          </div>
          
          <div class="mb-4">
            <label class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
              Default Era
            </label>
            <select 
              bind:value={timelineConfig.defaultEra} 
              on:change={notifyChanges}
              class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-l text-sm text-neutral-900 dark:text-neutral-100"
            >
              {#each timelineConfig.eras as era}
                <option value={era.name}>{era.name} ({era.startYear}-{era.endYear})</option>
              {/each}
            </select>
            <p class="mt-1 text-xs text-neutral-500 dark:text-neutral-400">
              The default era to display when the user first visits
            </p>
          </div>
          
          <div class="mb-4">
            <label class="flex items-center text-sm font-medium text-neutral-700 dark:text-neutral-300">
              <input 
                type="checkbox" 
                bind:checked={timelineConfig.showEraDescriptions} 
                on:change={notifyChanges}
                class="mr-2 h-4 w-4"
              />
              Show Era Descriptions
            </label>
            <p class="mt-1 ml-6 text-xs text-neutral-500 dark:text-neutral-400">
              When enabled, era descriptions will be shown in tooltips on the timeline
            </p>
          </div>
        </div>
        
        <div class="card bg-white dark:bg-neutral-800 p-5 rounded-lg border border-neutral-200 dark:border-neutral-700">
          <h3 class="font-medium text-lg text-black/80 dark:text-white/80 mb-4">Restore Defaults</h3>
          <p class="text-sm text-neutral-600 dark:text-neutral-400 mb-4">
            Reset the timeline configuration to its default settings.
          </p>
          
          <button 
            class="py-2 px-4 bg-amber-500 hover:bg-amber-600 text-white font-medium rounded-md transition-colors flex items-center"
            on:click={restoreDefaults}
          >
            <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 mr-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
            </svg>
            Restore Default Configuration
          </button>
        </div>
      </div>
    
    <!-- Eras Tab -->
    {:else if activeSection === 'eras'}
      <div class="eras-section space-y-6">
        <div class="card bg-white dark:bg-neutral-800 p-5 rounded-lg border border-neutral-200 dark:border-neutral-700">
          <div class="flex justify-between items-center mb-4">
            <h3 class="font-medium text-lg text-black/80 dark:text-white/80">Timeline Eras</h3>
            <button 
              class="py-1.5 px-3 bg-[var(--primary)] hover:opacity-90 text-white font-medium rounded-md transition-opacity text-sm flex items-center"
              on:click={addEra}
            >
              <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 mr-1" viewBox="0 0 20 20" fill="currentColor">
                <path fill-rule="evenodd" d="M10 5a1 1 0 011 1v3h3a1 1 0 110 2h-3v3a1 1 0 11-2 0v-3H6a1 1 0 110-2h3V6a1 1 0 011-1z" clip-rule="evenodd" />
              </svg>
              Add Era
            </button>
          </div>
          
          <div class="timeline-preview mb-6">
            <label class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-2">
              Timeline Preview
            </label>
            <div class="relative h-12 bg-neutral-100 dark:bg-neutral-800 rounded-lg overflow-hidden">
              {#each timelineConfig.eras as era}
                <!-- Calculate position and width based on years -->
                {@const totalYears = timelineConfig.eras.reduce((max, e) => Math.max(max, e.endYear), 0) - 
                                    timelineConfig.eras.reduce((min, e) => Math.min(min, e.startYear), Infinity)}
                {@const eraStart = era.startYear - timelineConfig.eras.reduce((min, e) => Math.min(min, e.startYear), Infinity)}
                {@const eraWidth = era.endYear - era.startYear}
                {@const leftPercent = (eraStart / totalYears) * 100}
                {@const widthPercent = (eraWidth / totalYears) * 100}
                
                <div 
                  class="absolute h-6 top-3 rounded-lg flex items-center justify-center text-xs text-white font-medium overflow-hidden"
                  style="left: {leftPercent}%; width: {widthPercent}%; background-color: {era.color};"
                >
                  {era.name}
                </div>
              {/each}
            </div>
          </div>
          
          <div class="space-y-3">
            {#each timelineConfig.eras as era, index}
              <div class="flex justify-between items-center p-3 rounded-lg border border-neutral-200 dark:border-neutral-700">
                <div class="flex items-center">
                  <div class="w-4 h-4 rounded-full mr-3" style="background-color: {era.color};"></div>
                  <div>
                    <div class="font-medium">{era.name}</div>
                    <div class="text-xs text-neutral-500 dark:text-neutral-400">{era.startYear} - {era.endYear}</div>
                  </div>
                </div>
                <div class="flex space-x-1">
                  <button 
                    class="p-1.5 text-neutral-500 hover:text-neutral-700 dark:hover:text-neutral-300 rounded"
                    on:click={() => moveEraUp(index)}
                    disabled={index === 0}
                    class:opacity-50={index === 0}
                  >
                    <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 10l7-7m0 0l7 7m-7-7v18" />
                    </svg>
                  </button>
                  <button 
                    class="p-1.5 text-neutral-500 hover:text-neutral-700 dark:hover:text-neutral-300 rounded"
                    on:click={() => moveEraDown(index)}
                    disabled={index === timelineConfig.eras.length - 1}
                    class:opacity-50={index === timelineConfig.eras.length - 1}
                  >
                    <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 14l-7 7m0 0l-7-7m7 7V3" />
                    </svg>
                  </button>
                  <button 
                    class="p-1.5 text-neutral-500 hover:text-[var(--primary)] rounded"
                    on:click={() => editEra(index)}
                  >
                    <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                    </svg>
                  </button>
                  <button 
                    class="p-1.5 text-neutral-500 hover:text-red-500 rounded"
                    on:click={() => deleteEra(index)}
                  >
                    <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                    </svg>
                  </button>
                </div>
              </div>
            {/each}
          </div>
        </div>
      </div>
    
    <!-- Display Options Tab -->
    {:else if activeSection === 'display'}
      <div class="display-section space-y-6">
        <div class="card bg-white dark:bg-neutral-800 p-5 rounded-lg border border-neutral-200 dark:border-neutral-700">
          <h3 class="font-medium text-lg text-black/80 dark:text-white/80 mb-4">Timeline Display Options</h3>
          
          <div class="mb-4">
            <label class="flex items-center text-sm font-medium text-neutral-700 dark:text-neutral-300">
              <input 
                type="checkbox" 
                bind:checked={timelineConfig.displayOptions.showYearLabels} 
                on:change={notifyChanges}
                class="mr-2 h-4 w-4"
              />
              Show Year Labels
            </label>
          </div>
          
          <div class="mb-4">
            <label class="flex items-center text-sm font-medium text-neutral-700 dark:text-neutral-300">
              <input 
                type="checkbox" 
                bind:checked={timelineConfig.displayOptions.showEraLabels} 
                on:change={notifyChanges}
                class="mr-2 h-4 w-4"
              />
              Show Era Labels
            </label>
          </div>
          
          <div class="mb-4">
            <label class="flex items-center text-sm font-medium text-neutral-700 dark:text-neutral-300">
              <input 
                type="checkbox" 
                bind:checked={timelineConfig.displayOptions.highlightCurrentYear} 
                on:change={notifyChanges}
                class="mr-2 h-4 w-4"
              />
              Highlight Current Year
            </label>
          </div>
          
          <div class="mb-4">
            <label class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
              Current Year
            </label>
            <input 
              type="number" 
              bind:value={timelineConfig.displayOptions.currentYear} 
              on:input={notifyChanges}
              min="1900" 
              max="2100" 
                class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm text-neutral-800 dark:text-neutral-200"
            />
            <p class="mt-1 text-xs text-neutral-500 dark:text-neutral-400">
              Default is the current year, but you can override it for your content
            </p>
          </div>
          
          <div class="mb-4">
            <label class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
              Year Label Spacing
            </label>
            <input 
              type="number" 
              bind:value={timelineConfig.displayOptions.yearSpacing} 
              on:input={notifyChanges}
              min="1" 
              max="50" 
                class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm text-neutral-800 dark:text-neutral-200"
            />
            <p class="mt-1 text-xs text-neutral-500 dark:text-neutral-400">
              Years between each label on the timeline (e.g., 10 = show every 10th year)
            </p>
          </div>
          
          <div class="mb-4">
            <label class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
              Timeline Height (px)
            </label>
            <input 
              type="number" 
              bind:value={timelineConfig.displayOptions.timelineHeight} 
              on:input={notifyChanges}
              min="2" 
              max="20" 
                class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm text-neutral-800 dark:text-neutral-200"
            />
          </div>
        </div>
      </div>
    {/if}
  </div>
  
  <!-- Era Editor Modal -->
  {#if showEraEditor}
    <div class="fixed inset-0 bg-black/50 dark:bg-black/60 z-50 flex items-center justify-center">
      <div class="bg-white dark:bg-neutral-800 rounded-lg max-w-md w-full p-6 shadow-lg">
        <h3 class="text-lg font-semibold text-black/80 dark:text-white/80 mb-4">
          {editingEra.isNew ? 'Add Era' : 'Edit Era'}
        </h3>
        
        <div class="mb-4">
          <label class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
            Era Name
          </label>
          <input 
            type="text" 
            bind:value={editingEra.data.name} 
              class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm text-neutral-800 dark:text-neutral-200"
            placeholder="e.g., past, present, future"
          />
        </div>
        
        <div class="grid grid-cols-2 gap-4 mb-4">
          <div>
            <label class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
              Start Year
            </label>
            <input 
              type="number" 
              bind:value={editingEra.data.startYear} 
              min="1900" 
              max="2100" 
                class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm text-neutral-800 dark:text-neutral-200"
            />
          </div>
          
          <div>
            <label class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
              End Year
            </label>
            <input 
              type="number" 
              bind:value={editingEra.data.endYear} 
              min="1900" 
              max="2100" 
                class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm text-neutral-800 dark:text-neutral-200"
            />
          </div>
        </div>
        
        <div class="mb-4">
          <label class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
            Color
          </label>
          <div class="flex items-center space-x-3">
            <input 
              type="color" 
              bind:value={editingEra.data.color} 
              class="h-10 w-10 border-0 rounded p-0"
            />
            <input 
              type="text" 
              bind:value={editingEra.data.color} 
              class="flex-1 px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm"
              placeholder="#3b82f6"
            />
          </div>
        </div>
        
        <div class="mb-6">
          <label class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
            Description
          </label>
          <textarea 
            bind:value={editingEra.data.description} 
            rows="3" 
              class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm text-neutral-800 dark:text-neutral-200"
            placeholder="A short description of this era"
          ></textarea>
        </div>
        
        <div class="flex justify-end space-x-3">
          <button 
            class="py-2 px-4 bg-neutral-200 dark:bg-neutral-700 hover:bg-neutral-300 dark:hover:bg-neutral-600 text-neutral-700 dark:text-neutral-200 font-medium rounded-md transition-colors"
            on:click={() => showEraEditor = false}
          >
            Cancel
          </button>
          
          <button 
            class="py-2 px-4 bg-[var(--primary)] hover:opacity-90 text-white font-medium rounded-md transition-opacity flex items-center"
            on:click={saveEra}
          >
            {editingEra.isNew ? 'Add Era' : 'Save Changes'}
          </button>
        </div>
      </div>
    </div>
  {/if}
</div>