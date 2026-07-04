<script>
  import { createEventDispatcher } from 'svelte';
  
  // Props
  export let aboutConfig;
  export let show = false;
  
  // State
  let exportStatus = {
    processing: false,
    error: null,
    success: false
  };
  
  // Event dispatcher
  const dispatch = createEventDispatcher();
  
  // Function to close the dialog
  function closeDialog() {
    dispatch('close');
  }
  
  // Format the type imports
  function formatTypeImports() {
    return `// Import types
import type { 
  AboutConfig,
  TeamSectionConfig,
  ContentSectionConfig,
  ContactSectionConfig
} from '../types/aboutconfig';`;
  }
  
  // Function to generate config file content
  function generateConfigFileContent() {
    try {
      // Generate about config content with types
      let aboutConfigContent = `${formatTypeImports()}

// About page configuration
export const aboutConfig: AboutConfig = ${JSON.stringify(aboutConfig, null, 2)
        .replace(/"([^"]+)":/g, '$1:')}`;
        
      return aboutConfigContent;
    } catch (error) {
      exportStatus.error = `Error generating configuration: ${error.message}`;
      console.error('Config generation error:', error);
      return '';
    }
  }
  
  // Function to download configuration file
  async function downloadConfigFile() {
    try {
      exportStatus.processing = true;
      exportStatus.error = null;
      
      const configContent = generateConfigFileContent();
      if (!configContent) return;
      
      // Create and download the config file
      downloadFile('about.config.ts', configContent);
      
      exportStatus.success = true;
      setTimeout(() => {
        exportStatus.success = false;
      }, 3000);
    } catch (error) {
      exportStatus.error = `Error exporting configuration: ${error.message}`;
      console.error('Export error:', error);
    } finally {
      exportStatus.processing = false;
    }
  }
  
  // Helper function to download a file
  function downloadFile(filename, content) {
    const blob = new Blob([content], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => {
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    }, 100);
  }
</script>

{#if show}
  <div class="fixed inset-0 bg-black/50 dark:bg-black/60 z-50 flex items-center justify-center">
    <div class="bg-white dark:bg-neutral-800 rounded-lg max-w-2xl w-full overflow-auto shadow-lg">
      <div class="p-5">
        <h3 class="text-xl font-semibold text-black/80 dark:text-white/80 mb-2">Export About Configuration</h3>
        <p class="text-neutral-600 dark:text-neutral-400 mb-4">
          Download your about page configuration to save it to your project. This file should be placed in your project's config directory.
        </p>
        
        <!-- Instructions -->
        <div class="bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800/30 rounded-md p-3 text-amber-800 dark:text-amber-200 text-sm mb-6">
          <div class="flex">
            <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 mr-2 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            </svg>
            <div>
              <p class="font-medium">Important:</p>
              <p class="mt-1">Download this file and place it in your project's <code>src/config/</code> directory as <code>about.config.ts</code>. This enables the about page to use your configured settings.</p>
            </div>
          </div>
        </div>
        
        <!-- Preview (Optional) -->
        <div class="mb-6">
          <div class="flex justify-between items-center mb-2">
            <h4 class="font-medium text-neutral-700 dark:text-neutral-300">Configuration Overview</h4>
          </div>
          <div class="bg-neutral-50 dark:bg-neutral-900 p-3 rounded-md border border-neutral-200 dark:border-neutral-700 text-sm">
            <div class="grid grid-cols-2 gap-4">
              <div>
                <p class="font-medium text-neutral-700 dark:text-neutral-300">Enabled Sections:</p>
                <ul class="text-neutral-500 dark:text-neutral-400 mt-1 list-disc pl-4">
                  {#if aboutConfig.team.enabled}
                    <li>Team Section</li>
                  {/if}
                  {#if aboutConfig.content.enabled}
                    <li>Content Section</li>
                  {/if}
                  {#if aboutConfig.contact.enabled}
                    <li>Contact Section</li>
                  {/if}
                </ul>
              </div>
              <div>
                <p class="font-medium text-neutral-700 dark:text-neutral-300">Key Settings:</p>
                <ul class="text-neutral-500 dark:text-neutral-400 mt-1 list-disc pl-4">
                  <li>Team layout: {aboutConfig.team.layout}</li>
                  <li>Columns: {aboutConfig.team.columns.desktop} (desktop)</li>
                  {#if aboutConfig.content.showTableOfContents}
                    <li>Table of Contents: Enabled</li>
                  {/if}
                </ul>
              </div>
            </div>
          </div>
        </div>
        
        <!-- Status Messages -->
        {#if exportStatus.error}
          <div class="bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-300 p-3 rounded-md mb-4">
            {exportStatus.error}
          </div>
        {/if}
        
        {#if exportStatus.success}
          <div class="bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-300 p-3 rounded-md mb-4">
            Configuration file exported successfully! Remember to save it to your project directory.
          </div>
        {/if}
        
        <!-- Action Buttons -->
        <div class="flex justify-end space-x-3 mt-6 pt-4 border-t border-neutral-200 dark:border-neutral-700">
          <button 
            type="button"
            class="px-4 py-2 border border-neutral-300 dark:border-neutral-600 text-neutral-700 dark:text-neutral-300 rounded-md hover:bg-neutral-50 dark:hover:bg-neutral-700 transition-colors"
            on:click={closeDialog}
          >
            Close
          </button>
          
          <button 
            type="button"
            class="px-4 py-2 bg-[var(--primary)] hover:opacity-90 text-white font-medium rounded-md transition-opacity flex items-center disabled:opacity-60"
            on:click={downloadConfigFile}
            disabled={exportStatus.processing}
          >
            {#if exportStatus.processing}
              <svg class="animate-spin mr-2 h-4 w-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
              </svg>
              Processing...
            {:else}
              <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 mr-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
              </svg>
              Download about.config.ts
            {/if}
          </button>
        </div>
      </div>
    </div>
  </div>
{/if}
