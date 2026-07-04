<script>
  import { createEventDispatcher } from 'svelte';
  import GithubAuthForm from './GithubAuthForm.svelte';
  import { createGitHubService } from '../../../lib/github-service';
  
  // Props
  export let siteConfig;
  export let navBarConfig;
  export let profileConfig;
  export let licenseConfig;
  export let timelineConfig;
  export let avatarConfig;
  export let communityConfig;
  export let aboutConfig;
  export let postCardConfig;
  export let bannerConfig;
  export let originalConfigValues;
  export let hasChanges = false;
  
  // State
  let githubService = createGitHubService();
  let isGitHubAuthenticated = false;
  let showGitHubAuthForm = false;
  let isCommitting = false;
  let commitStatus = { success: false, error: null };
  let showDeployOptions = false;
  let githubToken = '';
  
  // Event dispatcher
  const dispatch = createEventDispatcher();
  
  // Initialize on component mount
  export function initialize() {
    // Check GitHub authentication status
    isGitHubAuthenticated = githubService.isAuthenticated();
    
    // Set GitHub repository settings if needed
    if (!githubService.config) {
      githubService = createGitHubService({
        // These should match your GitHub repository details
        owner: 'your-github-username', // Update with your GitHub username
        repo: 'your-repo-name',        // Update with your repository name
        branch: 'main',                // Update with your branch name
        configPath: 'src/config',
        postsPath: 'src/content'
      });
    }
  }
  
  // Show GitHub auth form
  function showGitHubAuth() {
    showGitHubAuthForm = true;
  }
  
  // Handle GitHub authentication
  async function handleGitHubAuth(event) {
    // Get token from event if provided, otherwise use the bound value
    const token = event && event.detail ? event.detail : githubToken;
    
    if (!token) {
      commitStatus.error = 'Please enter a valid token';
      return;
    }
    
    try {
      isCommitting = true;
      commitStatus.error = null;
      
      // Authenticate with GitHub
      const success = githubService.authenticate(token);
      
      if (success) {
        // Test the token with a simple API call
        try {
          await githubService.getFile('README.md');
          isGitHubAuthenticated = true;
          showGitHubAuthForm = false;
          commitStatus.success = true;
          
          // Show success message
          setTimeout(() => {
            commitStatus.success = false;
          }, 3000);
        } catch (error) {
          console.error('Token validation error:', error);
          if (error.message.includes('401')) {
            commitStatus.error = 'Authentication failed. Please check your token permissions.';
          } else if (error.message.includes('404')) {
            commitStatus.error = 'Repository or README.md not found. Check your repository settings.';
          } else {
            commitStatus.error = `Token validation error: ${error.message}`;
          }
          githubService.logout(); // Clear the invalid token
        }
      } else {
        commitStatus.error = 'Failed to authenticate';
      }
    } catch (error) {
      console.error('Authentication error:', error);
      commitStatus.error = error.message || 'Failed to authenticate';
    } finally {
      isCommitting = false;
    }
  }
  
  // Handle GitHub logout
  function handleGitHubLogout() {
    githubService.logout();
    isGitHubAuthenticated = false;
    showDeployOptions = false;
  }
  
  // Handle constant references in the config
  function preserveConstants(configObj) {
    // Create a deep copy to avoid modifying the original
    const config = JSON.parse(JSON.stringify(configObj));
    
    // Check if defaultTheme exists and handle it specially
    if (config.defaultTheme) {
      // Check if the defaultTheme is already a string constant reference
      if (typeof config.defaultTheme === 'string' && 
          (config.defaultTheme === 'LIGHT_MODE' || 
           config.defaultTheme === 'DARK_MODE' || 
           config.defaultTheme === 'AUTO_MODE')) {
        // If it's already a constant name, wrap it for our formatter
        config.defaultTheme = `__CONSTANT_${config.defaultTheme.toLowerCase()}__`;
      } else {
        // Otherwise, use the string value
        const themeValue = config.defaultTheme;
        config.defaultTheme = `__CONSTANT_${themeValue}__`;
      }
    }
    
    // Add handling for other constants here if needed
    
    return config;
  }
  
  // Format a config object into TypeScript code
  function formatConfigObject(configName, configObj) {
    // Create a more precise formatter that preserves empty arrays and objects
    function formatWithPreservation(obj, indent = 2, level = 0) {
      const spaces = ' '.repeat(indent * level);
      const nextSpaces = ' '.repeat(indent * (level + 1));
      
      if (obj === null) return 'null';
      if (obj === undefined) return 'undefined';
      
      if (Array.isArray(obj)) {
        // Empty array becomes []
        if (obj.length === 0) return '[]';
        
        // Array with items gets formatted with proper indentation
        const items = obj.map(item => `${nextSpaces}${formatWithPreservation(item, indent, level + 1)}`);
        return `[\n${items.join(',\n')}\n${spaces}]`;
      }
      
      if (typeof obj === 'object') {
        // Empty object becomes {}
        const keys = Object.keys(obj);
        if (keys.length === 0) return '{}';
        
        // Object with properties gets formatted with proper indentation
        const items = keys.map(key => {
          const keyStr = /^[a-zA-Z_$][a-zA-Z0-9_$]*$/.test(key) ? key : `"${key}"`;
          return `${nextSpaces}${keyStr}: ${formatWithPreservation(obj[key], indent, level + 1)}`;
        });
        
        return `{\n${items.join(',\n')}\n${spaces}}`;
      }
      
      if (typeof obj === 'string') {
        // Check if the string is a special constant
        if (obj.startsWith('__CONSTANT_') && obj.endsWith('__')) {
          return obj.substring(11, obj.length - 2); // Remove the __CONSTANT_ and __ parts
        }
        return `"${obj.replace(/"/g, '\\"')}"`;
      }
      
      // For numbers, booleans, etc.
      return String(obj);
    }
    
    if (configName === 'siteConfig') {
      const processedConfig = preserveConstants(configObj);
      
      let formattedConfig = formatWithPreservation(processedConfig);
      // Replace constants
      formattedConfig = formattedConfig.replace(/"__CONSTANT_light__"/g, 'LIGHT_MODE')
                                        .replace(/"__CONSTANT_dark__"/g, 'DARK_MODE')
                                        .replace(/"__CONSTANT_auto__"/g, 'AUTO_MODE');
      return formattedConfig;
    } else if (configName === 'navBarConfig') {
      // Handle special LinkPreset enum values
      let formattedConfig = formatWithPreservation(configObj);
      formattedConfig = formattedConfig.replace(/"LinkPreset\.([a-zA-Z]+)"/g, 'LinkPreset.$1');
      return formattedConfig;
    } else {
      // Generic handling for other config types
      return formatWithPreservation(configObj);
    }
  }
  
  // Update config.ts file with all changes
  async function updateMainConfigFile(changes) {
    // First retrieve the current file
    const currentFile = await githubService.getFile('src/config/config.ts');
    if (!currentFile) {
      throw new Error('Could not retrieve the current config.ts file');
    }
    
    let fileContent = currentFile.content;
    
    // Ensure necessary imports are present
    if (!fileContent.includes('import { AUTO_MODE, DARK_MODE, LIGHT_MODE }')) {
      // Add import at top of file
      fileContent = `import { AUTO_MODE, DARK_MODE, LIGHT_MODE } from '@constants/constants.ts'\n\n${fileContent}`;
    }
    
    // Ensure LinkPreset is properly imported
    if (changes.some(c => c.name === 'navBarConfig')) {
      // If file doesn't have LinkPreset import at all
      if (!fileContent.includes('import { LinkPreset }')) {
        // Check if file already has import type statement
        if (fileContent.includes('import type {')) {
          fileContent = fileContent.replace(
            /import type {/,
            'import { LinkPreset } from \'../types/config\'\nimport type {'
          );
        } else {
          // Add it at the top of the file
          fileContent = `import { LinkPreset } from '../types/config'\n${fileContent}`;
        }
      }
    }
    
    // For each changed config, update its section in the file
    for (const config of changes) {
      const formattedConfig = formatConfigObject(config.name, config.obj);
      
      // Create a more precise regex that matches the export declaration and its value
      const regexPattern = new RegExp(`export const ${config.name}[\\s\\S]*?(?=\\n\\nexport const|$)`, 'g');
      
      if (regexPattern.test(fileContent)) {
        // Update existing config section
        fileContent = fileContent.replace(
          regexPattern,
          `export const ${config.name}: ${config.typeName} = ${formattedConfig}`
        );
      } else {
        // Append new config section if it doesn't exist
        fileContent += `\n\nexport const ${config.name}: ${config.typeName} = ${formattedConfig}`;
      }
    }
    
    // Save the updated file
    return githubService.commitFile(
      'src/config/config.ts', 
      fileContent, 
      `Update ${changes.map(c => c.name).join(', ')} in config.ts`
    );
  }
  
  // Update standalone config files
  async function updateStandaloneConfigFile(config) {
    // Generate standalone file content based on config type
    let fileContent = '';
    
    if (config.name === 'timelineConfig') {
      fileContent = `// TimelineConfig.ts - Central configuration for all timeline services
import type { TimelineConfig } from '../types/timelineconfig'

export const timelineConfig: TimelineConfig = ${formatConfigObject(config.name, config.obj)}`;
    } 
    else if (config.name === 'avatarConfig') {
      fileContent = `// Import type - use import type syntax to fix verbatimModuleSyntax error
import type { ImageMetadata } from 'astro'

// Define the avatar configuration type
export interface AvatarConfig {
avatarList: string[]
homeAvatar: string
animationInterval: number
}

/**
* Avatar configuration for the site
* Controls which avatars are used for the home page and posts
*/
export const avatarConfig: AvatarConfig = ${formatConfigObject(config.name, config.obj)}`;
    }
    else if (config.name === 'communityConfig') {
      // Create a specialized format that matches your current file structure
      fileContent = `// Import types
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
export const communityConfig: CommunityConfig = ${formatConfigObject(config.name, config.obj)}`;
    }
    else if (config.name === 'aboutConfig') {
      fileContent = `// Import types
import type { 
AboutConfig,
TeamSectionConfig,
ContentSectionConfig,
ContactSectionConfig
} from '../types/aboutconfig';

// About page configuration
export const aboutConfig: AboutConfig = ${formatConfigObject(config.name, config.obj)}`;
    }
    else if (config.name === 'postCardConfig') {
        fileContent = `// Configuration for PostCard components and friend post integration

    // Base PostCard configuration
    export interface PostCardConfig {
      // Layout options
      layout: {
        imagePosition: 'right' | 'top'; // Position of the image
        imageSizePercentage: number; // Size as percentage (e.g., 28 for 28%)
        cardBorderRadius: string; // Border radius for the card
        showEnterButton: boolean; // Whether to show the enter button
      };
      // Styling options
      styling: {
        titleSize: string; // Title font size class
        descriptionLines: number; // Number of lines to show in description
        animationEnabled: boolean; // Whether to enable load animations
      };
      // Content display options
      content: {
        showCategory: boolean;
        showTags: boolean;
        showUpdateDate: boolean;
        showWordCount: boolean;
        showReadTime: boolean;
        hideTagsOnMobile: boolean;
      };
    }

    // Friend post specific configuration
    export interface FriendPostConfig {
      // Friend styling options
      friendStyling: {
        indicatorType: 'border' | 'badge' | 'background'; // How to visually indicate friend posts
        indicatorColor: string; // Color for the indicator
        showFriendAvatar: boolean; // Whether to show friend's avatar
        avatarSize: string; // Size of the avatar
      };
    // Attribution options
      attribution: {
        showAttribution: boolean; // Whether to show attribution
        attributionText: string; // Text template for attribution
        linkToFriendSite: boolean; // Whether to link to friend's site
      };
      // Integration behavior
      behavior: {
        sortingMethod: 'date' | 'source'; // How to sort mixed posts
        mergeWithLocalPosts: boolean; // Whether to merge with local posts or show separately
      };
    }

    // Combined configuration
    export interface PostCardConfigs {
      localPosts: PostCardConfig;
      friendPosts: PostCardConfig & FriendPostConfig;
    }

    // Export the configuration
    export const postCardConfig: PostCardConfigs = ${formatConfigObject(config.name, config.obj)}`;
    } 
    else if (config.name === 'bannerConfig') {
        fileContent = `// Import type - use import type syntax to fix verbatimModuleSyntax error
import type { ImageMetadata } from 'astro'

// Import banner images
// These paths should match your actual banner image locations
import banner1 from 'src/assets/banner/0001.png'
import banner2 from 'src/assets/banner/0002.png'
import banner3 from 'src/assets/banner/0003.png'
import banner4 from 'src/assets/banner/0004.png'
import banner5 from 'src/assets/banner/0005.png'
import banner6 from 'src/assets/banner/0006.png'
import banner7 from 'src/assets/banner/0007.png'
import banner8 from 'src/assets/banner/0008.png'

// Define the banner configuration type
export interface BannerConfig {
  // List of banner images for animation
  bannerList: ImageMetadata[]
  
  // Default banner for static usage
  defaultBanner: ImageMetadata
  
  // Animation settings
  animation: {
    enabled: boolean
    interval: number            // Milliseconds between transitions
    transitionDuration: number  // Milliseconds for fade transition
    direction: 'forward' | 'reverse' | 'alternate'
  }
  
  // Layout settings
  layout: {
    height: {
      desktop: string          // CSS value (e.g., '50vh')
      mobile: string           // CSS value (e.g., '30vh')
    }
    overlap: {
      desktop: string          // CSS value (e.g., '3.5rem')
      mobile: string           // CSS value (e.g., '2rem')
    }
    maxWidth: number           // Maximum width in pixels
  }
  
  // Visual settings
  visual: {
    objectFit: 'cover' | 'contain' | 'fill'
    objectPosition: string     // CSS position value
    applyGradientOverlay: boolean
    gradientOverlay: string    // CSS gradient value
    borderRadius: string       // CSS border-radius value
  }
  
  // Fallback settings (used if images fail to load)
  fallback: {
    enabled: boolean
    type: 'color' | 'gradient'
    value: string              // CSS color or gradient
  }
}

/**
 * Banner configuration for the site
 * Controls which images are used for the animated banner
 */
export const bannerConfig: BannerConfig = ${formatConfigObject(config.name, config.obj)
          .replace(/"bannerList": \[\s*"([^"]+)",/g, 'bannerList: [\n    banner1,')
          .replace(/"banner(\d+)",/g, 'banner$1,')
          .replace(/"defaultBanner": "banner(\d+)"/g, 'defaultBanner: banner$1')
          .replace(/"forward"/g, "'forward'")
          .replace(/"reverse"/g, "'reverse'")
          .replace(/"alternate"/g, "'alternate'")
          .replace(/"cover"/g, "'cover'")
          .replace(/"contain"/g, "'contain'")
          .replace(/"fill"/g, "'fill'")
          .replace(/"color"/g, "'color'")
          .replace(/"gradient"/g, "'gradient'")}

/**
 * Get appropriate banner dimensions based on screen size
 * @returns Object with height and overlap values
 */
export function getResponsiveBannerDimensions(isMobile: boolean = false): {
  height: string;
  overlap: string;
} {
  return {
    height: isMobile ? bannerConfig.layout.height.mobile : bannerConfig.layout.height.desktop,
    overlap: isMobile ? bannerConfig.layout.overlap.mobile : bannerConfig.layout.overlap.desktop
  };
}

/**
 * Get CSS for fallback banner
 * @returns CSS string for background
 */
export function getFallbackBannerCSS(): string {
  if (!bannerConfig.fallback.enabled) return '';
  
  return bannerConfig.fallback.type === 'gradient' 
    ? bannerConfig.fallback.value
    : \`\${bannerConfig.fallback.value}\`;
}

/**
 * Get animation settings for banner
 * @returns Object with animation settings
 */
export function getBannerAnimationSettings(): {
  enabled: boolean;
  interval: number;
  transitionDuration: number;
  direction: string;
} {
  return {
    enabled: bannerConfig.animation.enabled,
    interval: bannerConfig.animation.interval,
    transitionDuration: bannerConfig.animation.transitionDuration,
    direction: bannerConfig.animation.direction
  };
}`;
    }

    // Save the standalone file
    return githubService.commitFile(
      `src/config/${config.filename}`, 
      fileContent, 
      `Update ${config.name} configuration`
    );
  }
  
  // Save configs to GitHub
  async function saveConfigsToGitHub() {
    if (!isGitHubAuthenticated) {
      commitStatus.error = 'Please authenticate with GitHub first';
      return;
    }
    
    try {
      isCommitting = true;
      commitStatus.error = null;
      
      // Track which configs have changed
      const mainConfigChanges = [];
      const standaloneConfigChanges = [];
      
      // Check which configs in the main file have changed
      if (JSON.stringify(siteConfig) !== originalConfigValues.siteConfig) {
        mainConfigChanges.push({ 
          name: 'siteConfig', 
          obj: siteConfig, 
          typeName: 'SiteConfig' 
        });
      }
      
      if (JSON.stringify(navBarConfig) !== originalConfigValues.navBarConfig) {
        mainConfigChanges.push({ 
          name: 'navBarConfig', 
          obj: navBarConfig, 
          typeName: 'NavBarConfig' 
        });
      }
      
      if (JSON.stringify(profileConfig) !== originalConfigValues.profileConfig) {
        mainConfigChanges.push({ 
          name: 'profileConfig', 
          obj: profileConfig, 
          typeName: 'ProfileConfig' 
        });
      }
      
      if (JSON.stringify(licenseConfig) !== originalConfigValues.licenseConfig) {
        mainConfigChanges.push({ 
          name: 'licenseConfig', 
          obj: licenseConfig, 
          typeName: 'LicenseConfig' 
        });
      }
      
      // Check which standalone config files have changed
      if (JSON.stringify(timelineConfig) !== originalConfigValues.timelineConfig) {
        standaloneConfigChanges.push({ 
          name: 'timelineConfig', 
          obj: timelineConfig, 
          filename: 'timelineconfig.ts' 
        });
      }
      
      if (JSON.stringify(avatarConfig) !== originalConfigValues.avatarConfig) {
        standaloneConfigChanges.push({ 
          name: 'avatarConfig', 
          obj: avatarConfig, 
          filename: 'avatar.config.ts' 
        });
      }
      
      if (JSON.stringify(communityConfig) !== originalConfigValues.communityConfig) {
        standaloneConfigChanges.push({ 
          name: 'communityConfig', 
          obj: communityConfig, 
          filename: 'community.config.ts' 
        });
      }
      
      if (JSON.stringify(aboutConfig) !== originalConfigValues.aboutConfig) {
        standaloneConfigChanges.push({ 
          name: 'aboutConfig', 
          obj: aboutConfig, 
          filename: 'about.config.ts' 
        });
      }
      
      if (JSON.stringify(postCardConfig) !== originalConfigValues.postCardConfig) {
        standaloneConfigChanges.push({ 
          name: 'postCardConfig', 
          obj: postCardConfig, 
          filename: 'postcard.config.ts' 
        });
      }
      
      if (JSON.stringify(bannerConfig) !== originalConfigValues.bannerConfig) {
        standaloneConfigChanges.push({ 
          name: 'bannerConfig', 
          obj: bannerConfig, 
          filename: 'banner.config.ts' 
        });
      }
      
      // If no configs have changed, inform the user
      if (mainConfigChanges.length === 0 && standaloneConfigChanges.length === 0) {
        commitStatus.error = 'No configuration changes detected to commit';
        isCommitting = false;
        return;
      }
      
      console.log(`Saving configuration changes...`);
      
      // Update the main config.ts file if needed
      if (mainConfigChanges.length > 0) {
        await updateMainConfigFile(mainConfigChanges);
        console.log(`Updated ${mainConfigChanges.length} configs in main config.ts file`);
      }
      
      // Update standalone config files if needed
      for (const config of standaloneConfigChanges) {
        await updateStandaloneConfigFile(config);
        console.log(`Saved ${config.filename}`);
      }
      
      // Notify parent that changes were saved and values should be updated
      dispatch('configsaved', {
        success: true,
        message: 'Configurations saved successfully to GitHub'
      });
      
      // Reset hasChanges flag (this is also done in the parent)
      // hasChanges = false;
      
      // Show success and deploy options
      commitStatus.success = true;
      showDeployOptions = true;
      
      // Show success message
      setTimeout(() => {
        commitStatus.success = false;
      }, 3000);
    } catch (error) {
      console.error('Error saving configs to GitHub:', error);
      
      // Provide more detailed error messages
      if (error.message.includes('401')) {
        commitStatus.error = 'Authentication failed. Please refresh your GitHub token.';
      } else if (error.message.includes('404')) {
        commitStatus.error = 'Repository or file not found. Check your repository settings.';
      } else {
        commitStatus.error = `Failed to save to GitHub: ${error.message}`;
      }
      
      // Notify parent of error
      dispatch('configsaved', {
        success: false,
        error: error.message
      });
    } finally {
      isCommitting = false;
    }
  }
  
  // Trigger site rebuild
  async function triggerSiteRebuild() {
    if (!isGitHubAuthenticated) {
      commitStatus.error = 'Please authenticate with GitHub first';
      return;
    }
    
    try {
      isCommitting = true;
      commitStatus.error = null;
      
      // Add a small delay to ensure all commits are processed
      // This prevents triggering a rebuild while commits are still being processed
      await new Promise(resolve => setTimeout(resolve, 1000));
      
      // Trigger the GitHub Action workflow for rebuilding the site
      // Make sure this matches your actual workflow filename
      await githubService.triggerWorkflow('deploy.yml');
      
      // Update UI status
      commitStatus.success = true;
      showDeployOptions = false;
      
      // Notify parent that site rebuild was triggered
      dispatch('deploy', {
        success: true,
        message: 'Site rebuild triggered successfully'
      });
      
      // Show success message
      setTimeout(() => {
        commitStatus.success = false;
      }, 3000);
    } catch (error) {
      console.error('Error triggering rebuild:', error);
      
      if (error.message.includes('404')) {
        commitStatus.error = `Failed to trigger rebuild: Workflow file not found. Make sure 'deploy.yml' exists in your repository's .github/workflows directory.`;
      } else {
        commitStatus.error = `Failed to trigger rebuild: ${error.message}`;
      }
      
      // Notify parent of error
      dispatch('deploy', {
        success: false,
        error: error.message
      });
    } finally {
      isCommitting = false;
    }
  }
</script>

<!-- GitHub Integration Panel -->
<div class="bg-white dark:bg-neutral-800 border border-neutral-200 dark:border-neutral-700 rounded-lg p-5">
  <h3 class="text-lg font-medium text-black/80 dark:text-white/80 mb-4">GitHub Integration</h3>
  
  {#if !isGitHubAuthenticated}
    <div class="bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800/30 rounded-md p-4 text-blue-800 dark:text-blue-200 mb-4">
      <div class="flex">
        <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 mr-2 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
        <div>
          <p class="font-medium">Connect to GitHub</p>
          <p class="mt-1">Authenticate with GitHub to save your changes directly to your repository.</p>
        </div>
      </div>
    </div>
    
    {#if showGitHubAuthForm}
      <GithubAuthForm 
        isAuthenticating={isCommitting}
        errorMessage={commitStatus.error}
        bind:token={githubToken}
        on:authenticate={handleGitHubAuth}
        on:cancel={() => showGitHubAuthForm = false}
        on:error={(e) => commitStatus.error = e.detail}
      />
    {:else}
      <button 
        on:click={showGitHubAuth}
        class="py-2 px-4 bg-neutral-800 dark:bg-neutral-200 hover:bg-neutral-900 dark:hover:bg-neutral-300 text-white dark:text-neutral-800 font-medium rounded-md transition-colors flex items-center"
      >
        <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 mr-2" viewBox="0 0 24 24">
          <path fill="currentColor" d="M12 .297c-6.63 0-12 5.373-12 12 0 5.303 3.438 9.8 8.205 11.385.6.113.82-.258.82-.577 0-.285-.01-1.04-.015-2.04-3.338.724-4.042-1.61-4.042-1.61C4.422 18.07 3.633 17.7 3.633 17.7c-1.087-.744.084-.729.084-.729 1.205.084 1.838 1.236 1.838 1.236 1.07 1.835 2.809 1.305 3.495.998.108-.776.417-1.305.76-1.605-2.665-.3-5.466-1.332-5.466-5.93 0-1.31.465-2.38 1.235-3.22-.135-.303-.54-1.523.105-3.176 0 0 1.005-.322 3.3 1.23.96-.267 1.98-.399 3-.405 1.02.006 2.04.138 3 .405 2.28-1.552 3.285-1.23 3.285-1.23.645 1.653.24 2.873.12 3.176.765.84 1.23 1.91 1.23 3.22 0 4.61-2.805 5.625-5.475 5.92.42.36.81 1.096.81 2.22 0 1.606-.015 2.896-.015 3.286 0 .315.21.69.825.57C20.565 22.092 24 17.592 24 12.297c0-6.627-5.373-12-12-12" />
        </svg>
        Connect to GitHub
      </button>
    {/if}
  {:else}
    <div class="bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800/30 rounded-md p-4 text-green-800 dark:text-green-200 mb-4">
      <div class="flex">
        <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 mr-2 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
        </svg>
        <div>
          <p class="font-medium">Connected to GitHub</p>
          <p class="mt-1">You can now push your changes directly to your repository.</p>
        </div>
      </div>
    </div>
    
    <div class="flex flex-col sm:flex-row gap-3">
      <button 
        on:click={saveConfigsToGitHub}
        disabled={isCommitting || !hasChanges}
        class="py-2 px-4 bg-neutral-800 dark:bg-neutral-200 hover:bg-neutral-900 dark:hover:bg-neutral-300 text-white dark:text-neutral-800 font-medium rounded-md transition-colors flex items-center justify-center disabled:opacity-50"
      >
        {#if isCommitting && !showDeployOptions}
          <svg class="animate-spin -ml-1 mr-2 h-4 w-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
          </svg>
          Committing to GitHub...
        {:else}
          <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 mr-2" viewBox="0 0 24 24">
            <path fill="currentColor" d="M12 .297c-6.63 0-12 5.373-12 12 0 5.303 3.438 9.8 8.205 11.385.6.113.82-.258.82-.577 0-.285-.01-1.04-.015-2.04-3.338.724-4.042-1.61-4.042-1.61C4.422 18.07 3.633 17.7 3.633 17.7c-1.087-.744.084-.729.084-.729 1.205.084 1.838 1.236 1.838 1.236 1.07 1.835 2.809 1.305 3.495.998.108-.776.417-1.305.76-1.605-2.665-.3-5.466-1.332-5.466-5.93 0-1.31.465-2.38 1.235-3.22-.135-.303-.54-1.523.105-3.176 0 0 1.005-.322 3.3 1.23.96-.267 1.98-.399 3-.405 1.02.006 2.04.138 3 .405 2.28-1.552 3.285-1.23 3.285-1.23.645 1.653.24 2.873.12 3.176.765.84 1.23 1.91 1.23 3.22 0 4.61-2.805 5.625-5.475 5.92.42.36.81 1.096.81 2.22 0 1.606-.015 2.896-.015 3.286 0 .315.21.69.825.57C20.565 22.092 24 17.592 24 12.297c0-6.627-5.373-12-12-12" />
          </svg>
          {hasChanges ? 'Commit to GitHub' : 'No Changes to Commit'}
        {/if}
      </button>
      
      {#if showDeployOptions}
        <button 
          on:click={triggerSiteRebuild}
          disabled={isCommitting}
          class="py-2 px-4 bg-[var(--primary)] hover:opacity-90 text-white font-medium rounded-md transition-opacity flex items-center justify-center disabled:opacity-50"
        >
          {#if isCommitting}
            <svg class="animate-spin -ml-1 mr-2 h-4 w-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
            </svg>
            Triggering Rebuild...
          {:else}
            <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 mr-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
            </svg>
            Deploy Changes
          {/if}
        </button>
      {/if}
      
      <button 
        on:click={handleGitHubLogout}
        class="py-2 px-4 bg-red-600 hover:bg-red-700 text-white font-medium rounded-md transition-colors flex items-center justify-center"
      >
        <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 mr-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
        </svg>
        Disconnect
      </button>
    </div>
    
    {#if commitStatus.success}
      <div class="mt-3 text-sm text-green-600 dark:text-green-400 flex items-center">
        <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 mr-2" viewBox="0 0 20 20" fill="currentColor">
          <path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd" />
        </svg>
        {showDeployOptions ? 'Changes committed successfully!' : 'Site rebuild triggered successfully!'}
      </div>
    {/if}
    
    {#if commitStatus.error}
      <div class="mt-3 text-sm text-red-600 dark:text-red-400">
        {commitStatus.error}
      </div>
    {/if}
  {/if}
  
  <div class="mt-4 text-sm text-neutral-500 dark:text-neutral-400">
    <p>This integration automatically commits your configuration changes to your GitHub repository and can trigger a site rebuild.</p>
  </div>
</div>