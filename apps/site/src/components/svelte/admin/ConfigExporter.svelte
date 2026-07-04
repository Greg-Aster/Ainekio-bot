<script>
  import { createEventDispatcher } from 'svelte';
  
  // Props
  export let siteConfig;
  export let navBarConfig;
  export let profileConfig;
  export let licenseConfig;
  export let timelineConfig;
  export let avatarConfig;
  export let communityConfig;
  export let aboutConfig;
  export let show = false;
  
  // State
  let selectedConfigs = {
    mainConfig: true,   // config.ts (contains siteConfig, navBarConfig, profileConfig, licenseConfig)
    timelineConfig: false,
    avatarConfig: false,
    communityConfig: false,
    aboutConfig: false
  };
  
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
  
  // Function to handle constant references in the config
  function preserveConstants(configObj) {
    // Create a deep copy to avoid modifying the original
    const config = JSON.parse(JSON.stringify(configObj));
    
    // Check if defaultTheme exists and handle it specially
    if (config.defaultTheme) {
      // Store the original value to determine which constant to use
      const themeValue = config.defaultTheme;
      
      // Mark it for replacement with the appropriate constant
      config.defaultTheme = `__CONSTANT_${themeValue}__`;
    }
    
    return config;
  }
  
  // Function to generate config file content
  function generateConfigFileContent() {
    // Apply constant preservation to siteConfig
    const processedSiteConfig = preserveConstants(siteConfig);
    
    // Generate main config.ts content
    let mainConfigContent = `import type {
  LicenseConfig,
  NavBarConfig,
  ProfileConfig,
  SiteConfig,
} from '../types/config'
import { LinkPreset } from '../types/config'
import { AUTO_MODE, DARK_MODE, LIGHT_MODE } from '@constants/constants.ts'


export const siteConfig: SiteConfig = ${JSON.stringify(processedSiteConfig, null, 2)
      .replace(/"([^"]+)":/g, '$1:')
      .replace(/"__CONSTANT_light__"/g, 'LIGHT_MODE')
      .replace(/"__CONSTANT_dark__"/g, 'DARK_MODE')
      .replace(/"__CONSTANT_auto__"/g, 'AUTO_MODE')}

export const navBarConfig: NavBarConfig = ${JSON.stringify(navBarConfig, null, 2)
      .replace(/"([^"]+)":/g, '$1:')
      .replace(/"LinkPreset\.([a-zA-Z]+)"/g, 'LinkPreset.$1')}

export const profileConfig: ProfileConfig = ${JSON.stringify(profileConfig, null, 2)
      .replace(/"([^"]+)":/g, '$1:')}

export const licenseConfig: LicenseConfig = ${JSON.stringify(licenseConfig, null, 2)
      .replace(/"([^"]+)":/g, '$1:')}`;

    // Generate timelineconfig.ts content
    const timelineConfigContent = `// TimelineConfig.ts - Central configuration for all timeline services

export const timelineConfig = ${JSON.stringify(timelineConfig, null, 2)
      .replace(/"([^"]+)":/g, '$1:')}`;
      
    // Generate avatar.config.ts content
    const avatarConfigContent = `// Import type - use import type syntax to fix verbatimModuleSyntax error
      import type { ImageMetadata } from 'astro'

      // Import avatar images
      ${avatarConfig.avatarList.map((path, index) => 
      `import avatar${index + 1} from '${path}'`
      ).join('\n')}

      // Define the avatar configuration type
      export interface AvatarConfig {
      avatarList: ImageMetadata[]
      homeAvatar: ImageMetadata
      animationInterval: number
      }

      /**
       * Avatar configuration for the site
       * Controls which avatars are used for the home page and posts
       */
      export const avatarConfig: AvatarConfig = {
      // List of all available avatars for post pages and rotation
      avatarList: [
          ${avatarConfig.avatarList.map((_, index) => `avatar${index + 1}`).join(',\n    ')}
      ],
      
      // Avatar to use on the home page (site owner)
      homeAvatar: ${avatarConfig.homeAvatar ? 
          `avatar${avatarConfig.avatarList.findIndex(path => path === avatarConfig.homeAvatar) + 1}` : 
          'avatar1'},
      
      // Animation interval in milliseconds
      animationInterval: ${Number(avatarConfig.animationInterval) || 3500}
      };

      /**
       * Get a consistent avatar index for a given post slug
       * This ensures the same post always shows the same avatar
       */
      export function getAvatarIndexFromSlug(slug: string = '', avatarCount: number): number {
      if (!slug) return 0 // Default to first avatar if no slug
      
      // Simple hash function to get consistent avatar for each slug
      let hash = 0
      for (let i = 0; i < slug.length; i++) {
          hash = ((hash << 5) - hash) + slug.charCodeAt(i)
          hash = hash & hash // Convert to 32bit integer
      }
      
      // Ensure positive index and map to available avatars
      return Math.abs(hash) % avatarCount
      }`;  

    // Generate community.config.ts content
    const communityConfigContent = `// Import types
import type { 
CommunityConfig,
DiscordConfig,
ContactConfig,
NewsletterConfig,
EventsConfig,
GuidelinesConfig,
HeroConfig
} from '../types/communityconfig';

// Community page configuration
export const communityConfig: CommunityConfig = ${JSON.stringify(communityConfig, null, 2)
      .replace(/"([^"]+)":/g, '$1:')}`;

    // Generate about.config.ts content
    const aboutConfigContent = `// Import types
import type { 
AboutConfig,
TeamSectionConfig,
ContentSectionConfig,
ContactSectionConfig
} from '../types/aboutconfig';

// About page configuration
export const aboutConfig: AboutConfig = ${JSON.stringify(aboutConfig, null, 2)
      .replace(/"([^"]+)":/g, '$1:')}`;

    return {
      mainConfigContent,
      timelineConfigContent,
      avatarConfigContent,
      communityConfigContent,
      aboutConfigContent
    };
  }
  
  // Function to download configuration files
  async function downloadConfigFiles() {
    try {
      exportStatus.processing = true;
      exportStatus.error = null;
      
      const { mainConfigContent, timelineConfigContent, avatarConfigContent, communityConfigContent, aboutConfigContent } = generateConfigFileContent();
      
      // Create and download the selected config files
      if (selectedConfigs.mainConfig) {
        downloadFile('config.ts', mainConfigContent);
      }
      
      if (selectedConfigs.timelineConfig) {
        downloadFile('timelineconfig.ts', timelineConfigContent);
      }
      
      if (selectedConfigs.avatarConfig) {
        downloadFile('avatar.config.ts', avatarConfigContent);
      }
      
      if (selectedConfigs.communityConfig) {
        downloadFile('community.config.ts', communityConfigContent);
      }
      
      if (selectedConfigs.aboutConfig) {
        downloadFile('about.config.ts', aboutConfigContent);
      }
      
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
        <h3 class="text-xl font-semibold text-black/80 dark:text-white/80 mb-2">Export Configuration Files</h3>
        <p class="text-neutral-600 dark:text-neutral-400 mb-4">
          Select which configuration files you want to download. These files should be saved to your project's config directory.
        </p>
        
        <div class="space-y-4 mb-6">
          <div class="flex items-center">
            <input 
              type="checkbox" 
              id="main-config" 
              bind:checked={selectedConfigs.mainConfig}
              class="h-4 w-4 text-[var(--primary)] border-neutral-300 dark:border-neutral-600 rounded" 
            />
            <label for="main-config" class="ml-2 block text-sm text-neutral-700 dark:text-neutral-300">
              config.ts - Main site configuration
              <span class="block text-xs text-neutral-500 dark:text-neutral-400 mt-0.5">
                Includes site settings, navigation, profile, and license information
              </span>
            </label>
          </div>
          
          <div class="flex items-center">
            <input 
              type="checkbox" 
              id="timeline-config" 
              bind:checked={selectedConfigs.timelineConfig}
              class="h-4 w-4 text-[var(--primary)] border-neutral-300 dark:border-neutral-600 rounded" 
            />
            <label for="timeline-config" class="ml-2 block text-sm text-neutral-700 dark:text-neutral-300">
              timelineconfig.ts - Timeline configuration
              <span class="block text-xs text-neutral-500 dark:text-neutral-400 mt-0.5">
                Includes timeline eras, settings, and behavior
              </span>
            </label>
          </div>
          
          <div class="flex items-center">
            <input 
              type="checkbox" 
              id="avatar-config" 
              bind:checked={selectedConfigs.avatarConfig}
              class="h-4 w-4 text-[var(--primary)] border-neutral-300 dark:border-neutral-600 rounded" 
            />
            <label for="avatar-config" class="ml-2 block text-sm text-neutral-700 dark:text-neutral-300">
              avatar.config.ts - Avatar configuration
              <span class="block text-xs text-neutral-500 dark:text-neutral-400 mt-0.5">
                Includes avatar settings, sequence, and animation options
              </span>
            </label>
          </div>
          
          <div class="flex items-center">
            <input 
              type="checkbox" 
              id="community-config" 
              bind:checked={selectedConfigs.communityConfig}
              class="h-4 w-4 text-[var(--primary)] border-neutral-300 dark:border-neutral-600 rounded" 
            />
            <label for="community-config" class="ml-2 block text-sm text-neutral-700 dark:text-neutral-300">
              community.config.ts - Community page configuration
              <span class="block text-xs text-neutral-500 dark:text-neutral-400 mt-0.5">
                Includes community sections, features, and form settings
              </span>
            </label>
          </div>
          
          <div class="flex items-center">
            <input 
              type="checkbox" 
              id="about-config" 
              bind:checked={selectedConfigs.aboutConfig}
              class="h-4 w-4 text-[var(--primary)] border-neutral-300 dark:border-neutral-600 rounded" 
            />
            <label for="about-config" class="ml-2 block text-sm text-neutral-700 dark:text-neutral-300">
              about.config.ts - About page configuration
              <span class="block text-xs text-neutral-500 dark:text-neutral-400 mt-0.5">
                Includes team, content, and contact section settings
              </span>
            </label>
          </div>
          
          <div class="flex items-center opacity-50 cursor-not-allowed">
            <input 
              type="checkbox" 
              id="banner-config" 
              disabled
              class="h-4 w-4 text-[var(--primary)] border-neutral-300 dark:border-neutral-600 rounded" 
            />
            <label for="banner-config" class="ml-2 block text-sm text-neutral-700 dark:text-neutral-300">
              banner.config.ts - Banner configuration
              <span class="block text-xs text-neutral-500 dark:text-neutral-400 mt-0.5">
                (Not yet implemented in the admin panel)
              </span>
            </label>
          </div>
        </div>
        
        <!-- Instructions -->
        <div class="bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800/30 rounded-md p-3 text-amber-800 dark:text-amber-200 text-sm mb-6">
          <div class="flex">
            <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 mr-2 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            </svg>
            <div>
              <p class="font-medium">Important:</p>
              <p class="mt-1">Download these files and replace the existing ones in your project's config directory. This is the only way to permanently save your configuration changes.</p>
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
            Configuration files exported successfully! Save them to your project directory.
          </div>
        {/if}
        
        <!-- Action Buttons -->
        <div class="flex justify-end space-x-3 mt-6 pt-4 border-t border-neutral-200 dark:border-neutral-700">
          <button 
            type="button"
            class="px-4 py-2 border border-neutral-300 dark:border-neutral-600 text-neutral-700 dark:text-neutral-300 rounded-md hover:bg-neutral-50 dark:hover:bg-neutral-700 transition-colors"
            on:click={closeDialog}
          >
            Cancel
          </button>
          
          <button 
            type="button"
            class="px-4 py-2 bg-[var(--primary)] hover:opacity-90 text-white font-medium rounded-md transition-opacity flex items-center disabled:opacity-60"
            on:click={downloadConfigFiles}
            disabled={exportStatus.processing || (!selectedConfigs.mainConfig && !selectedConfigs.timelineConfig && !selectedConfigs.avatarConfig && !selectedConfigs.communityConfig && !selectedConfigs.aboutConfig)}
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
              Download Files
            {/if}
          </button>
        </div>
      </div>
    </div>
  </div>
{/if}