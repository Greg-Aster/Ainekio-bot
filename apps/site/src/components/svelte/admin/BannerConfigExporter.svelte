<script>
  import { createEventDispatcher } from 'svelte';
  
  // Props
  export let bannerConfig;
  export let show = false;
  
  // Event dispatcher
  const dispatch = createEventDispatcher();
  
  // Function to close the dialog
  function closeDialog() {
    dispatch('close');
  }
  
  // Function to generate banner.config.ts content
  function generateBannerConfigContent() {
    // Create a string template for the banner.config.ts file
    let bannerConfigContent = `// Import type - use import type syntax to fix verbatimModuleSyntax error
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

// Banner type definitions
export type BannerType = 'standard' | 'video' | 'image' | 'timeline';

// Banner data type for each banner type
export interface StandardBannerData {
  // No additional data needed for standard banner
}

export interface VideoBannerData {
  videoId: string;
}

export interface ImageBannerData {
  imageUrl: string;
}

export interface TimelineBannerData {
  category: string;
  title?: string;
  startYear?: number;
  endYear?: number;
  background?: string;
  compact?: boolean;
  height?: string;
}

// Define the banner configuration type
export interface BannerConfig {
  // Default banner type for main pages
  defaultBannerType: BannerType;
  
  // Default banner data (differs based on banner type)
  defaultBannerData: StandardBannerData | VideoBannerData | ImageBannerData | TimelineBannerData;
  
  // List of banner images for animation (used for standard banner type)
  bannerList: ImageMetadata[]
  
  // Default banner for static usage (used for standard banner type)
  defaultBanner: ImageMetadata
  
  // Animation settings (used for standard banner type)
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
  
  // Navbar spacing settings
  navbarSpacing: {
    standard: string         // For standard animated banner
    timeline: string         // For timeline banner
    video: string            // For video banner
    image: string            // For image banner
  }
}

/**
 * Banner configuration for the site
 * Controls which images are used for the animated banner
 */
export const bannerConfig: BannerConfig = ${JSON.stringify({
      ...bannerConfig,
      // Ensure navbarSpacing exists even if it's not in the current config
      navbarSpacing: bannerConfig.navbarSpacing || {
        standard: '0',
        timeline: '4.5rem',
        video: '4.5rem',
        image: '4.5rem'
      }
    }, null, 2)
      .replace(/"([^"]+)":/g, '$1:')
      .replace(/"forward"/g, "'forward'")
      .replace(/"reverse"/g, "'reverse'")
      .replace(/"alternate"/g, "'alternate'")
      .replace(/"cover"/g, "'cover'")
      .replace(/"contain"/g, "'contain'")
      .replace(/"fill"/g, "'fill'")
      .replace(/"color"/g, "'color'")
      .replace(/"gradient"/g, "'gradient'")
      .replace(/"bannerList": \[\s*"([^"]+)",/g, 'bannerList: [\n    banner1,')
      .replace(/"banner(\d+)",/g, 'banner$1,')
      .replace(/"defaultBanner": "banner(\d+)"/g, 'defaultBanner: banner$1')}

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
}

/**
 * Helper function to determine if the default banner data is for a specific banner type
 */
export function isVideoBannerData(data: any): data is VideoBannerData {
  return data && 'videoId' in data && typeof data.videoId === 'string';
}

export function isImageBannerData(data: any): data is ImageBannerData {
  return data && 'imageUrl' in data && typeof data.imageUrl === 'string';
}

export function isTimelineBannerData(data: any): data is TimelineBannerData {
  return data && 'category' in data && typeof data.category === 'string';
}`;
    
    return bannerConfigContent;
  }
  
  // Function to download the banner config file
  function downloadBannerConfig() {
    const content = generateBannerConfigContent();
    const blob = new Blob([content], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'banner.config.ts';
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
        <h3 class="text-xl font-semibold text-black/80 dark:text-white/80 mb-2">Export Banner Configuration</h3>
        <p class="text-neutral-600 dark:text-neutral-400 mb-4">
          Download the banner configuration file to save your settings.
        </p>
        
        <!-- Instructions -->
        <div class="bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800/30 rounded-md p-3 text-amber-800 dark:text-amber-200 text-sm mb-6">
          <div class="flex">
            <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 mr-2 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            </svg>
            <div>
              <p class="font-medium">Important:</p>
              <p class="mt-1">Download this file and place it in your project's config directory (src/config/banner.config.ts). This is the only way to permanently save your banner configuration changes.</p>
            </div>
          </div>
        </div>
        
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
            class="px-4 py-2 bg-[var(--primary)] hover:opacity-90 text-white font-medium rounded-md transition-opacity flex items-center"
            on:click={downloadBannerConfig}
          >
            <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 mr-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
            </svg>
            Download Banner Config
          </button>
        </div>
      </div>
    </div>
  </div>
{/if}