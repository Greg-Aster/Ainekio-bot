<script>
    import { createEventDispatcher } from 'svelte';
    
    // Props
    export let era;
    export let onSave;
    export let onCancel;
    
    // Local state
    let formData = { ...era };
    let errors = {};
    let isNewEra = !era.key || era.key === '';
    
    // Event dispatcher
    const dispatch = createEventDispatcher();
    
    // Function to validate form
    function validateForm() {
      errors = {};
      
      if (!formData.key) {
        errors.key = "Era key is required";
      } else if (!/^[a-z0-9-]+$/.test(formData.key)) {
        errors.key = "Era key can only contain lowercase letters, numbers, and hyphens";
      }
      
      if (!formData.displayName) {
        errors.displayName = "Display name is required";
      }
      
      if (formData.startYear === undefined || formData.startYear === null) {
        errors.startYear = "Start year is required";
      }
      
      if (formData.endYear === undefined || formData.endYear === null) {
        errors.endYear = "End year is required";
      }
      
      if (formData.startYear >= formData.endYear) {
        errors.endYear = "End year must be greater than start year";
      }
      
      return Object.keys(errors).length === 0;
    }
    
    // Function to handle form submission
    function handleSubmit() {
      if (validateForm()) {
        const success = onSave(formData);
        if (success) {
          dispatch('saved', formData);
        }
      }
    }
    
    // Function to generate a slug from display name
    function generateSlug() {
      if (formData.displayName && isNewEra) {
        formData.key = formData.displayName
          .toLowerCase()
          .replace(/[^a-z0-9\s-]/g, '')
          .replace(/\s+/g, '-');
      }
    }
  </script>
  
  <div class="era-editor p-6">
    <h3 class="text-xl font-semibold text-black/80 dark:text-white/80 mb-4">
      {isNewEra ? 'Add New Era' : 'Edit Era'}
    </h3>
    
    <form on:submit|preventDefault={handleSubmit} class="space-y-4">
      <!-- Era Key -->
      <div>
        <label for="era-key" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
          Era Key <span class="text-red-500">*</span>
        </label>
        <div class="relative">
          <input 
            type="text" 
            id="era-key" 
            bind:value={formData.key}
            class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border {errors.key ? 'border-red-500' : 'border-neutral-300 dark:border-neutral-600'} rounded-md text-sm transition"
            placeholder="e.g. 'golden-age'"
            disabled={!isNewEra}
          />
          {#if isNewEra}
            <button 
              type="button"
              class="absolute right-2 top-1/2 -translate-y-1/2 text-xs text-neutral-500 hover:text-[var(--primary)] bg-neutral-100 dark:bg-neutral-600 rounded px-2 py-0.5"
              on:click={generateSlug}
            >
              Generate
            </button>
          {/if}
        </div>
        {#if errors.key}
          <p class="mt-1 text-sm text-red-500">{errors.key}</p>
        {:else}
          <p class="mt-1 text-xs text-neutral-500 dark:text-neutral-400">
            Unique identifier for this era. Use lowercase letters, numbers, and hyphens only.
          </p>
        {/if}
      </div>
      
      <!-- Display Name -->
      <div>
        <label for="display-name" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
          Display Name <span class="text-red-500">*</span>
        </label>
        <input 
          type="text" 
          id="display-name" 
          bind:value={formData.displayName}
          class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border {errors.displayName ? 'border-red-500' : 'border-neutral-300 dark:border-neutral-600'} rounded-md text-sm transition"
          placeholder="e.g. 'The Golden Age'"
        />
        {#if errors.displayName}
          <p class="mt-1 text-sm text-red-500">{errors.displayName}</p>
        {/if}
      </div>
      
      <!-- Year Range -->
      <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div>
          <label for="start-year" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
            Start Year <span class="text-red-500">*</span>
          </label>
          <input 
            type="number" 
            id="start-year" 
            bind:value={formData.startYear}
            class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border {errors.startYear ? 'border-red-500' : 'border-neutral-300 dark:border-neutral-600'} rounded-md text-sm transition"
            placeholder="e.g. 1000"
          />
          {#if errors.startYear}
            <p class="mt-1 text-sm text-red-500">{errors.startYear}</p>
          {/if}
        </div>
        
        <div>
          <label for="end-year" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
            End Year <span class="text-red-500">*</span>
          </label>
          <input 
            type="number" 
            id="end-year" 
            bind:value={formData.endYear}
            class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border {errors.endYear ? 'border-red-500' : 'border-neutral-300 dark:border-neutral-600'} rounded-md text-sm transition"
            placeholder="e.g. 2000"
          />
          {#if errors.endYear}
            <p class="mt-1 text-sm text-red-500">{errors.endYear}</p>
          {/if}
        </div>
      </div>
      
      <!-- Visualization Settings -->
      <div class="pt-2">
        <h4 class="text-md font-medium text-black/70 dark:text-white/70 mb-3">Visualization Settings</h4>
        
        <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label for="zoom-level" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
              Default Zoom Level
            </label>
            <input 
              type="number" 
              id="zoom-level" 
              bind:value={formData.zoomLevel}
              step="0.1"
              min="0.5"
              max="5"
              class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-l text-sm text-neutral-900 dark:text-neutral-100"
              placeholder="e.g. 2.5"
            />
            <p class="mt-1 text-xs text-neutral-500 dark:text-neutral-400">
              Zoom level when this era is selected (0.5-5)
            </p>
          </div>
          
          <div>
            <label for="pan-to-year" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
              Focus Year
            </label>
            <input 
              type="number" 
              id="pan-to-year" 
              bind:value={formData.panToYear}
              class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-l text-sm text-neutral-900 dark:text-neutral-100"
              placeholder="e.g. 1500"
            />
            <p class="mt-1 text-xs text-neutral-500 dark:text-neutral-400">
              Year to center on when this era is selected
            </p>
          </div>
        </div>
      </div>
      
      <!-- Background Image -->
      <div>
        <label for="background-image" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
          Background Image
        </label>
        <input 
          type="text" 
          id="background-image" 
          bind:value={formData.backgroundImage}
          class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-l text-sm text-neutral-900 dark:text-neutral-100"
          placeholder="/posts/timeline/golden-era.png"
        />
        <p class="mt-1 text-xs text-neutral-500 dark:text-neutral-400">
          Path to the background image for this era
        </p>
      </div>
      
      <!-- CSS Classes -->
      <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div>
          <label for="color-class" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
            Color Class
          </label>
          <input 
            type="text" 
            id="color-class" 
            bind:value={formData.colorClass}
            class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-l text-sm text-neutral-900 dark:text-neutral-100"
            placeholder="e.g. 'text-blue-500'"
          />
          <p class="mt-1 text-xs text-neutral-500 dark:text-neutral-400">
            Tailwind CSS class for era text color
          </p>
        </div>
        
        <div>
          <label for="badge-class" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
            Badge Class
          </label>
          <input 
            type="text" 
            id="badge-class" 
            bind:value={formData.badgeClass}
            class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-l text-sm text-neutral-900 dark:text-neutral-100"
            placeholder="e.g. 'bg-blue-100 text-blue-800'"
          />
          <p class="mt-1 text-xs text-neutral-500 dark:text-neutral-400">
            Tailwind CSS classes for era badge styling
          </p>
        </div>
      </div>
      
      <!-- Buttons -->
      <div class="flex justify-end space-x-3 pt-4 border-t border-neutral-200 dark:border-neutral-700">
        <button 
          type="button"
          class="px-4 py-2 border border-neutral-300 dark:border-neutral-600 text-neutral-700 dark:text-neutral-300 rounded-md hover:bg-neutral-50 dark:hover:bg-neutral-700 transition-colors"
          on:click={onCancel}
        >
          Cancel
        </button>
        
        <button 
          type="submit"
          class="px-4 py-2 bg-[var(--primary)] hover:opacity-90 text-white font-medium rounded-md transition-opacity"
        >
          {isNewEra ? 'Create Era' : 'Save Changes'}
        </button>
      </div>
    </form>
  </div>