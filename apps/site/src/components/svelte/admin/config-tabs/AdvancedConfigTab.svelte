<script lang="ts">
  import { createEventDispatcher } from 'svelte';
  
  // Props - receive all configs
  export let siteConfig;
  export let navBarConfig;
  export let profileConfig;
  export let licenseConfig;
  export let timelineConfig;
  export let avatarConfig;
  
  // Local state
  let showExportOptions = false;
  let exportFormat = 'astro';
  let fileName = 'site-config';
  let statusMessage = { text: '', type: '' };
  
  // Event dispatcher
  const dispatch = createEventDispatcher();
  
  // Format options
  const exportFormats = [
    { value: 'astro', label: 'Astro Configuration (.ts)' },
    { value: 'json', label: 'JSON Configuration (.json)' }
  ];
  
  // Function to generate the config file content
  function generateConfigContent() {
    try {
      // Combine all configs into one object for export
      const fullConfig = {
        siteConfig,
        navBarConfig,
        profileConfig,
        licenseConfig,
        timelineConfig,
        avatarConfig
      };
      
      if (exportFormat === 'astro') {
        // Generate TypeScript configuration
        return `// Site Configuration - Generated on ${new Date().toLocaleString()}
import type { SiteConfig, NavBarConfig, ProfileConfig, LicenseConfig, TimelineConfig, AvatarConfig } from '../types';

// Site Configuration
export const siteConfig: SiteConfig = ${JSON.stringify(siteConfig, null, 2)};

// Navigation Configuration
export const navBarConfig: NavBarConfig = ${JSON.stringify(navBarConfig, null, 2)};

// Profile Configuration
export const profileConfig: ProfileConfig = ${JSON.stringify(profileConfig, null, 2)};

// License Configuration
export const licenseConfig: LicenseConfig = ${JSON.stringify(licenseConfig, null, 2)};

// Timeline Configuration
export const timelineConfig: TimelineConfig = ${JSON.stringify(timelineConfig, null, 2)};

// Avatar Configuration
export const avatarConfig: AvatarConfig = ${JSON.stringify(avatarConfig, null, 2)};
`;
      } else {
        // Generate JSON configuration
        return JSON.stringify(fullConfig, null, 2);
      }
    } catch (error) {
      statusMessage = { 
        text: `Error generating config: ${error.message}`, 
        type: 'error' 
      };
      return '';
    }
  }
  
  // Function to download the configuration file
  function downloadConfig() {
    try {
      const content = generateConfigContent();
      if (!content) return;
      
      const extension = exportFormat === 'astro' ? 'ts' : 'json';
      const fileNameWithExt = `${fileName}.${extension}`;
      const blob = new Blob([content], { type: 'text/plain' });
      const url = URL.createObjectURL(blob);
      
      // Create download link and trigger click
      const a = document.createElement('a');
      a.href = url;
      a.download = fileNameWithExt;
      document.body.appendChild(a);
      a.click();
      
      // Clean up
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      
      statusMessage = { 
        text: `Configuration exported as ${fileNameWithExt}`, 
        type: 'success' 
      };
      
      // Hide the success message after 3 seconds
      setTimeout(() => {
        if (statusMessage.type === 'success') {
          statusMessage = { text: '', type: '' };
        }
      }, 3000);
    } catch (error) {
      statusMessage = { 
        text: `Error exporting config: ${error.message}`, 
        type: 'error' 
      };
    }
  }
  
  // Function to copy config to clipboard
  function copyToClipboard() {
    try {
      const content = generateConfigContent();
      if (!content) return;
      
      navigator.clipboard.writeText(content).then(() => {
        statusMessage = { 
          text: 'Configuration copied to clipboard', 
          type: 'success' 
        };
        
        // Hide the success message after 3 seconds
        setTimeout(() => {
          if (statusMessage.type === 'success') {
            statusMessage = { text: '', type: '' };
          }
        }, 3000);
      });
    } catch (error) {
      statusMessage = { 
        text: `Error copying to clipboard: ${error.message}`, 
        type: 'error' 
      };
    }
  }
  
  // Function to open export dialog
  function showExportDialog() {
    showExportOptions = true;
  }
  
  // Reset all configurations to default (placeholder)
  function resetToDefaults() {
    if (confirm('Are you sure you want to reset all configurations to default values? This cannot be undone.')) {
      // This would typically call a service or API to reset configs
      // For now, it's just a placeholder
      statusMessage = { 
        text: 'This is a placeholder. In a real implementation, this would reset your configs to default values.', 
        type: 'info' 
      };
    }
  }
</script>

<div class="advanced-config-tab">
  <div class="mb-6">
    <h2 class="text-xl font-semibold text-black/80 dark:text-white/80 mb-4">Advanced Configuration</h2>
    <p class="text-neutral-600 dark:text-neutral-400 mb-4">
      Export your site configuration for backup or to use in development.
    </p>
  </div>
  
  <!-- Configuration Card -->
  <div class="bg-white dark:bg-neutral-800 border border-neutral-200 dark:border-neutral-700 rounded-lg p-5 mb-6">
    <h3 class="text-lg font-medium text-black/80 dark:text-white/80 mb-3">Configuration Export</h3>
    <p class="text-neutral-600 dark:text-neutral-400 mb-4">
      Export your site configuration as a TypeScript or JSON file for use in your Astro project.
    </p>
    
    <button 
      class="py-2 px-4 bg-[var(--primary)] hover:opacity-90 text-white font-medium rounded-md transition-opacity flex items-center"
      on:click={showExportDialog}
    >
      <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 mr-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
      </svg>
      Export Configuration
    </button>
  </div>
  
  <!-- Development Tools Card -->
  <div class="bg-white dark:bg-neutral-800 border border-neutral-200 dark:border-neutral-700 rounded-lg p-5 mb-6">
    <h3 class="text-lg font-medium text-black/80 dark:text-white/80 mb-3">Development Tools</h3>
    <p class="text-neutral-600 dark:text-neutral-400 mb-4">
      Additional tools for developers working with site configurations.
    </p>
    
    <div class="flex flex-col space-y-3 sm:flex-row sm:space-y-0 sm:space-x-3">
      <button 
        class="py-2 px-4 bg-neutral-100 dark:bg-neutral-700 hover:bg-neutral-200 dark:hover:bg-neutral-600 text-neutral-700 dark:text-neutral-200 font-medium rounded-md transition-colors flex items-center"
        on:click={copyToClipboard}
      >
        <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 mr-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 5H6a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2v-1M8 5a2 2 0 002 2h2a2 2 0 002-2M8 5a2 2 0 012-2h2a2 2 0 012 2m0 0h2a2 2 0 012 2v3m2 4H10m0 0l3-3m-3 3l3 3" />
        </svg>
        Copy to Clipboard
      </button>
      
      <button 
        class="py-2 px-4 bg-amber-50 dark:bg-amber-900/30 text-amber-700 dark:text-amber-300 border border-amber-200 dark:border-amber-700 hover:bg-amber-100 dark:hover:bg-amber-800/30 font-medium rounded-md transition-colors flex items-center"
        on:click={resetToDefaults}
      >
        <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 mr-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
        </svg>
        Reset to Defaults
      </button>
    </div>
  </div>
  
  <!-- Status Message -->
  {#if statusMessage.text}
    <div 
      class="mt-4 p-3 rounded-md {
        statusMessage.type === 'success' ? 'bg-green-50 dark:bg-green-900/20 text-green-600 dark:text-green-300 border border-green-200 dark:border-green-800/30' :
        statusMessage.type === 'error' ? 'bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-300 border border-red-200 dark:border-red-800/30' :
        'bg-blue-50 dark:bg-blue-900/20 text-blue-600 dark:text-blue-300 border border-blue-200 dark:border-blue-800/30'
      }"
    >
      <div class="flex">
        {#if statusMessage.type === 'success'}
          <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 mr-2 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
          </svg>
        {:else if statusMessage.type === 'error'}
          <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 mr-2 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
        {:else}
          <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 mr-2 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
        {/if}
        <span>{statusMessage.text}</span>
      </div>
    </div>
  {/if}
  
  <!-- Export Options Modal -->
  {#if showExportOptions}
    <div class="fixed inset-0 bg-black/50 dark:bg-black/60 z-50 flex items-center justify-center">
      <div class="bg-white dark:bg-neutral-800 rounded-lg max-w-md w-full p-6 shadow-lg">
        <h3 class="text-lg font-semibold text-black/80 dark:text-white/80 mb-4">Export Configuration</h3>
        
        <div class="mb-4">
          <label for="export-format" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
            Format
          </label>
          <select 
            id="export-format" 
            bind:value={exportFormat}
            class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-l text-sm text-neutral-900 dark:text-neutral-100"
          >
            {#each exportFormats as format}
              <option value={format.value}>{format.label}</option>
            {/each}
          </select>
        </div>
        
        <div class="mb-6">
          <label for="file-name" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
            File Name
          </label>
          <input 
            type="text" 
            id="file-name" 
            bind:value={fileName}
            class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-l text-sm text-neutral-900 dark:text-neutral-100 focus:ring-2 focus:ring-[var(--primary)] focus:border-transparent"
            placeholder="site-config"
          />
          <p class="mt-1 text-xs text-neutral-500 dark:text-neutral-400">
            Extension will be added automatically based on the selected format.
          </p>
        </div>
        
        <div class="flex justify-end space-x-3">
          <button 
            class="py-2 px-4 bg-neutral-200 dark:bg-neutral-700 hover:bg-neutral-300 dark:hover:bg-neutral-600 text-neutral-700 dark:text-neutral-200 font-medium rounded-md transition-colors"
            on:click={() => showExportOptions = false}
          >
            Cancel
          </button>
          
          <button 
            class="py-2 px-4 bg-[var(--primary)] hover:opacity-90 text-white font-medium rounded-md transition-opacity flex items-center"
            on:click={() => {
              downloadConfig();
              showExportOptions = false;
            }}
          >
            <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 mr-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
            </svg>
            Download
          </button>
        </div>
      </div>
    </div>
  {/if}
</div>