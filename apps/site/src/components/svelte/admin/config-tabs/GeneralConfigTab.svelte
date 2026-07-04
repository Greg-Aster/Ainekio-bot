<script>
    import { createEventDispatcher } from 'svelte';
    
    // Props
    export let siteConfig;
    export let licenseConfig;
    
    // Event dispatcher
    const dispatch = createEventDispatcher();
    
    // Available languages for dropdown
    const availableLanguages = [
      { code: 'en', name: 'English' },
      { code: 'es', name: 'Español' },
      { code: 'ja', name: 'Japanese (日本語)' },
      { code: 'ko', name: 'Korean (한국어)' },
      { code: 'th', name: 'Thai (ไทย)' },
      { code: 'zh_CN', name: 'Simplified Chinese (简体中文)' },
      { code: 'zh_TW', name: 'Traditional Chinese (繁體中文)' }
    ];
    
    // TOC depth options
    const tocDepthOptions = [
      { value: 1, label: 'Level 1 Headers Only' },
      { value: 2, label: 'Level 1-2 Headers' },
      { value: 3, label: 'Level 1-3 Headers' }
    ];
    
    // Handle changes to form fields
    function handleChange() {
      dispatch('change', { siteConfig, licenseConfig });
    }
  </script>
  
  <div class="general-settings space-y-6">
    <div>
      <h2 class="text-xl font-semibold text-black/80 dark:text-white/80 mb-4">Site Information</h2>
      
      <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div>
          <label for="site-title" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
            Site Title
          </label>
          <input 
            type="text" 
            id="site-title" 
            bind:value={siteConfig.title}
            on:change={handleChange}
            class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-l text-sm text-neutral-900 dark:text-neutral-100" 
            placeholder="Your Site Title"
          />
        </div>
        
        <div>
          <label for="site-subtitle" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
            Subtitle
          </label>
          <input 
            type="text" 
            id="site-subtitle" 
            bind:value={siteConfig.subtitle}
            on:change={handleChange}
            class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-l text-sm text-neutral-900 dark:text-neutral-100" 
            placeholder="Your site subtitle or tagline"
          />
        </div>
        
        <div>
          <label for="site-language" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
            Language
          </label>
          <select 
            id="site-language" 
            bind:value={siteConfig.lang}
            on:change={handleChange}
            class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-l text-sm text-neutral-900 dark:text-neutral-100"
          >
            {#each availableLanguages as language}
              <option value={language.code}>{language.name}</option>
            {/each}
          </select>
          <p class="mt-1 text-xs text-neutral-500 dark:text-neutral-400">
            Primary language for your site (affects translations)
          </p>
        </div>
      </div>
    </div>
    
    <!-- Table of Contents Settings -->
    <div class="pt-4 border-t border-neutral-200 dark:border-neutral-700">
      <h2 class="text-xl font-semibold text-black/80 dark:text-white/80 mb-4">Table of Contents</h2>
      
      <div class="space-y-4">
        <div class="flex items-center">
          <input 
            type="checkbox" 
            id="toc-enable" 
            bind:checked={siteConfig.toc.enable}
            on:change={handleChange}
            class="h-4 w-4 text-[var(--primary)] border-neutral-300 dark:border-neutral-600 rounded" 
          />
          <label for="toc-enable" class="ml-2 block text-sm text-neutral-700 dark:text-neutral-300">
            Enable Table of Contents on Post Pages
          </label>
        </div>
        
        <div>
          <label for="toc-depth" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
            TOC Depth
          </label>
          <select 
            id="toc-depth" 
            bind:value={siteConfig.toc.depth}
            on:change={handleChange}
            disabled={!siteConfig.toc.enable}
            class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-l text-sm text-neutral-900 dark:text-neutral-100 {!siteConfig.toc.enable ? 'opacity-50 cursor-not-allowed' : ''}"
          >
            {#each tocDepthOptions as option}
              <option value={option.value}>{option.label}</option>
            {/each}
          </select>
          <p class="mt-1 text-xs text-neutral-500 dark:text-neutral-400">
            How many levels of headings to display in the table of contents
          </p>
        </div>
      </div>
    </div>
    
    <!-- License Settings -->
    <div class="pt-4 border-t border-neutral-200 dark:border-neutral-700">
      <h2 class="text-xl font-semibold text-black/80 dark:text-white/80 mb-4">Content License</h2>
      
      <div class="space-y-4">
        <div class="flex items-center">
          <input 
            type="checkbox" 
            id="license-enable" 
            bind:checked={licenseConfig.enable}
            on:change={handleChange}
            class="h-4 w-4 text-[var(--primary)] border-neutral-300 dark:border-neutral-600 rounded" 
          />
          <label for="license-enable" class="ml-2 block text-sm text-neutral-700 dark:text-neutral-300">
            Display License Information
          </label>
        </div>
        
        <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label for="license-name" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
              License Name
            </label>
            <input 
              type="text" 
              id="license-name" 
              bind:value={licenseConfig.name}
              on:change={handleChange}
              disabled={!licenseConfig.enable}
              class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-l text-sm text-neutral-900 dark:text-neutral-100 {!licenseConfig.enable ? 'opacity-50 cursor-not-allowed' : ''}" 
              placeholder="e.g. CC BY-NC-SA 4.0"
            />
          </div>
          
          <div>
            <label for="license-url" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
              License URL
            </label>
            <input 
              type="url" 
              id="license-url" 
              bind:value={licenseConfig.url}
              on:change={handleChange}
              disabled={!licenseConfig.enable}
              class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-l text-sm text-neutral-900 dark:text-neutral-100 {!licenseConfig.enable ? 'opacity-50 cursor-not-allowed' : ''}" 
              placeholder="https://creativecommons.org/licenses/by-nc-sa/4.0/"
            />
          </div>
        </div>
        
        <div class="bg-neutral-50 dark:bg-neutral-800/30 p-4 rounded-lg border border-neutral-200 dark:border-neutral-700 text-sm text-neutral-600 dark:text-neutral-400">
          <p>
            Common Licenses:
          </p>
          <ul class="mt-2 space-y-1 list-disc pl-5">
            <li><span class="font-medium">CC BY-NC-SA 4.0</span> - Attribution-NonCommercial-ShareAlike</li>
            <li><span class="font-medium">CC BY-SA 4.0</span> - Attribution-ShareAlike</li>
            <li><span class="font-medium">CC BY 4.0</span> - Attribution</li>
            <li><span class="font-medium">MIT License</span> - Permissive</li>
          </ul>
        </div>
      </div>
    </div>
  </div>