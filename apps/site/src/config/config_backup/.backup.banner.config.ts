// Import type - use import type syntax to fix verbatimModuleSyntax error
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
export const bannerConfig: BannerConfig = {
  // List of all banner images for animation
  bannerList: [
    banner1,
    banner2,
    banner3,
    banner4,
    banner5,
    banner6,
    banner7,
    banner8
  ],
  
  // Default banner image (used for static banner or as first animation frame)
  defaultBanner: banner1,
  
  // Animation settings
  animation: {
    enabled: true,
    interval: 5000,            // 5 seconds between transitions
    transitionDuration: 1000,  // 1 second fade transition
    direction: 'alternate'     // Bounce back and forth through the images
  },
  
  // Layout settings
  layout: {
    height: {
      desktop: '50vh',         // 50% of viewport height on desktop
      mobile: '30vh'           // 30% of viewport height on mobile
    },
    overlap: {
      desktop: '3.5rem',       // Content overlap on desktop
      mobile: '2rem'           // Content overlap on mobile
    },
    maxWidth: 1920             // Max banner width in pixels
  },
  
  // Visual settings
  visual: {
    objectFit: 'cover',
    objectPosition: 'center',
    applyGradientOverlay: false,
    gradientOverlay: 'linear-gradient(to bottom, rgba(0,0,0,0.2), transparent)',
    borderRadius: '0'
  },
  
  // Fallback settings
  fallback: {
    enabled: true,
    type: 'gradient',
    value: 'linear-gradient(to bottom, var(--color-primary-light), var(--color-primary))'
  }
}

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
    : `${bannerConfig.fallback.value}`;
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