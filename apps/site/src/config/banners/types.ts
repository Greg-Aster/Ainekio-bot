/**
 * ===================================================================
 * BANNER TYPES CONFIGURATION - SHARED TYPE DEFINITIONS
 * ===================================================================
 *
 * This file contains all shared type definitions used across the banner system.
 * It centralizes type safety for all banner components and ensures consistency
 * across different banner implementations.
 *
 * TYPES DEFINED:
 * - BannerType: Union type of all available banner types
 * - Banner data interfaces for each banner type
 * - Mixed content types for video and image support in standard banners
 * - Helper interfaces for banner determination and configuration
 * - Link preview and icon definitions
 *
 * USAGE:
 * - Import specific types as needed: import type { BannerType, VideoBannerData } from './types'
 * - Use type guards from banner.config.ts for safe type checking
 * - Reference these types when creating new banner configurations
 *
 * MAINTENANCE NOTES:
 * - When adding new banner types, add them to the BannerType union
 * - Create corresponding data interface for new banner types
 * - Update BannerData union type to include new interfaces
 * ===================================================================
 */

// Import type for Astro image metadata
import type { ImageMetadata } from 'astro'

// =====================================================================
// CORE BANNER TYPE DEFINITIONS
// =====================================================================

/**
 * Available banner types for the site
 * Add new banner types to this union when implementing new banner features
 */
export type BannerType =
  | 'standard'
  | 'video'
  | 'image'
  | 'timeline'
  | 'assistant'
  | 'none'

// =====================================================================
// MIXED CONTENT TYPE DEFINITIONS FOR STANDARD BANNERS
// =====================================================================

/**
 * Video banner item configuration for mixed content
 * Used in standard banners that support both videos and images
 */
export interface VideoBannerItem {
  type: 'video'
  src: string // Path to video file (e.g., '/videos/banner1.webm')
  fallbackImage: ImageMetadata // Fallback image for unsupported browsers
  alt: string // Alt text for accessibility
  preload?: 'none' | 'metadata' | 'auto' // Video preload behavior
}

/**
 * Image banner item configuration for mixed content
 * Used in standard banners that support both videos and images
 */
export interface ImageBannerItem {
  type: 'image'
  src: ImageMetadata // Astro image metadata
  alt: string // Alt text for accessibility
}

/**
 * Union type for mixed banner content
 * Allows standard banners to contain both videos and images
 */
export type BannerItem = VideoBannerItem | ImageBannerItem

/**
 * Video-specific configuration for banner playback
 * Controls how videos behave in banner cycling
 */
export interface VideoBannerConfig {
  autoplay: boolean // Auto-play videos
  muted: boolean // Mute videos (required for autoplay)
  loop: boolean // Loop individual videos
  playsInline: boolean // Play inline on mobile
  controls: boolean // Show video controls
  preload: 'none' | 'metadata' | 'auto' // Default preload behavior
}

// =====================================================================
// BANNER DATA TYPE DEFINITIONS
// =====================================================================

/**
 * Standard banner configuration
 * Uses the bannerList array and animation settings from standard banner config
 * Now supports mixed video and image content through BannerItem[]
 */
export type StandardBannerData = {}

/**
 * Video banner configuration
 * For embedding YouTube videos as banners
 */
export interface VideoBannerData {
  videoId: string // YouTube video ID (the part after 'v=' in YouTube URLs)
}

/**
 * Image banner configuration
 * For static single images as banners
 */
export interface ImageBannerData {
  imageUrl: string // Direct URL to the image file
}

/**
 * Timeline banner configuration
 * For interactive timeline displays
 */
export interface TimelineBannerData {
  category: string // Timeline category (required)
  title?: string // Optional display title
  startYear?: number // Optional start year for timeline
  endYear?: number // Optional end year for timeline
  background?: string // Optional background image URL
  compact?: boolean // Optional compact display mode
  height?: string // Optional custom height (CSS value)
}

/**
 * Assistant banner configuration
 * For AI assistant (Bleepy) interactive banners
 */
export interface AssistantBannerData {
  imageUrl?: string // Optional background image for assistant banner
}

/**
 * None banner configuration
 * Used when no banner should be displayed
 */
export type NoneBannerData = {}

/**
 * Union type for all banner data types
 * Add new banner data interfaces to this union when creating new banner types
 */
export type BannerData =
  | StandardBannerData
  | VideoBannerData
  | ImageBannerData
  | TimelineBannerData
  | AssistantBannerData
  | NoneBannerData

// =====================================================================
// TYPE GUARD FUNCTIONS FOR MIXED CONTENT
// =====================================================================

/**
 * Type guard to check if banner item is a video
 * Ensures type safety when working with mixed content
 */
export function isVideoBannerItem(item: BannerItem): item is VideoBannerItem {
  return item.type === 'video'
}

/**
 * Type guard to check if banner item is an image
 * Ensures type safety when working with mixed content
 */
export function isImageBannerItem(item: BannerItem): item is ImageBannerItem {
  return item.type === 'image'
}

// =====================================================================
// HELPER TYPE DEFINITIONS
// =====================================================================

/**
 * Link preview data type for enhanced banner interactions
 * Used to show rich previews when hovering over clickable banners
 */
export interface LinkPreviewInfo {
  title: string
  description: string
  icon: string // Font Awesome icon name (without fa6-solid: prefix)
}

/**
 * Banner determination result type
 * Contains flags and current banner type information for layout decisions
 */
export interface BannerDeterminationResult {
  hasTimelineBanner: boolean
  hasVideoBanner: boolean
  hasImageBanner: boolean
  hasAssistantBanner: boolean
  hasStandardBanner: boolean
  hasPostBanner: boolean
  isStandardPage: boolean
  currentBannerType: BannerType
}

/**
 * Post data extraction result type
 * Extracted banner-related data from post frontmatter
 */
export interface PostBannerData {
  bannerLink: string
  customAvatar: string
  customName: string
  customBio: string
  slug: string
  wantsNoDefaultBanner: boolean
}

/**
 * Animation configuration for standard banners
 * Controls timing and behavior of banner cycling
 */
export interface BannerAnimationConfig {
  enabled: boolean
  interval: number // Milliseconds between transitions
  transitionDuration: number // Milliseconds for fade transition
  direction: 'forward' | 'reverse' | 'alternate'
  randomStart?: boolean // true = pick a random image on each page load
  // Added from standard.ts animationConfig
  pauseOnHover?: boolean
  pauseOnMobileTouch?: boolean
  resumeAfterNavigation?: boolean
  smoothTransitions?: boolean
  motion?: {
    enabled: boolean
    mode?:
      | 'zoom-in'
      | 'zoom-out'
      | 'pan-left'
      | 'pan-right'
      | 'pan-up'
      | 'pan-down'
      | 'pan-horizontal'
      | 'pan-vertical'
      | 'alternate'
      | 'random'
      | 'push-in'
      | 'push-out'
    duration?: number // Milliseconds per slide motion cycle
    scale?: number // Target max scale for zoom/pan effects
    panDistance?: number // Pan travel distance in percent
    easing?: string // CSS timing function
    alternate?: boolean // Flip direction between slides
  }
}

/**
 * Layout configuration for banner dimensions and positioning
 * Controls responsive sizing and spacing
 */
export interface BannerLayoutConfig {
  height: {
    desktop: string // CSS value (e.g., '50vh')
    mobile: string // CSS value (e.g., '30vh')
  }
  overlap: {
    desktop: string // CSS value (e.g., '3.5rem')
    mobile: string // CSS value (e.g., '2rem')
  }
  maxWidth: number // Maximum width in pixels
  noneBannerPlaceholderHeight?: string // Placeholder height for 'none' banner
  mainContentOffset: {
    desktop: string // Space between banner and main content on desktop
    mobile: string // Space between banner and main content on mobile
  }
  // Page overlap settings for different pages
  pageOverlaps: {
    home: {
      desktop: string
      mobile: string
    }
    post: {
      desktop: string
      mobile: string
    }
    archive: {
      desktop: string
      mobile: string
    }
    about: {
      desktop: string
      mobile: string
    }
  }
}

/**
 * Visual styling configuration for banners
 * Controls appearance and visual effects
 */
export interface BannerVisualConfig {
  objectFit: 'cover' | 'contain' | 'fill'
  objectPosition: string // CSS position value
  applyGradientOverlay: boolean
  gradientOverlay: string // CSS gradient value
  borderRadius: string // CSS border-radius value
}

/**
 * Fallback configuration for when banner images fail to load
 * Provides graceful degradation
 */
export interface BannerFallbackConfig {
  enabled: boolean
  type: 'color' | 'gradient'
  value: string // CSS color or gradient
}

/**
 * Navbar configuration for banner spacing
 * Controls spacing between navbar and different banner types
 */
export interface BannerNavbarConfig {
  height: {
    desktop: string // CSS value (e.g., '4.5rem')
    mobile: string // CSS value (e.g., '3.5rem')
  }
  spacing: {
    standard: string // For standard animated banner
    timeline: string // For timeline banner
    video: string // For video banner
    image: string // For image banner
    assistant: string // For assistant banner
    none: string // For none banner
  }
}

/**
 * Panel positioning configuration
 * Controls where main content panels appear relative to banners
 */
export interface BannerPanelConfig {
  top: {
    video: string // CSS value for video banner type
    image: string // CSS value for image banner type
    timeline: string // CSS value for timeline banner type
    standard: string // CSS value for standard banner type
    assistant: string // CSS value for assistant banner type
    none: string // CSS value for none banner type
  }
}

/**
 * Parallax effect configuration
 * Controls background parallax scrolling effects
 */
export interface BannerParallaxConfig {
  enabled: boolean
  scrollFactor: number // How much the parallax moves (e.g., -0.05)
  easingFactor: number // Smooth motion factor (e.g., 0.1)
}

/**
 * Comprehensive details for rendering a banner item's preview card.
 * This structure is intended to be populated by the config files
 * and consumed by bannerAnimation.ts for rendering.
 */
export interface BannerItemPreviewDetails {
  hasValidLink: boolean
  originalHref: string // The actual URL for navigation if a link is valid
  urlForDisplay: string // Formatted URL or pathname for display in the card
  previewTitle: string
  previewDescription: string
  previewIconSVG: string // The actual SVG string for the icon
  isVideoButton: boolean // True if the banner item is a video
}

/**
 * ⭐ NEW: Banner dimensions configuration interface
 * Centralizes all banner sizing and aspect ratio settings
 */
export interface BannerDimensionsConfig {
  aspectRatio: string // Default aspect ratio (e.g., "56.25%" for 16:9)
  maxWidth: string // Maximum banner width (e.g., "90vw")
  padding: string // Responsive padding (e.g., "2.5vw")
  containerSpacing: string // Space around banner containers
  borderRadius: string // Border radius for banner corners

  // Alternative aspect ratios for different use cases
  aspectRatios: {
    standard: string // 16:9 for standard banners
    video: string // 16:9 for videos
    image: string // 16:9 for images
    timeline: string // 16:9 for timeline
    assistant: string // 16:9 for assistant
    ultrawide: string // 21:9 ultrawide option
    square: string // 1:1 square option
    portrait: string // 3:4 portrait option
  }

  // Responsive overrides
  responsive: {
    mobile: {
      maxWidth: string // Mobile max width
      padding: string // Mobile padding
      aspectRatio?: string // Optional mobile aspect ratio override
    }
    desktop: {
      maxWidth?: string // Desktop max width override
    }
  }
}

/**
 * ⭐ UPDATED: Enhanced visual configuration interface
 * Now includes the unified dimensions system
 */
export interface BannerVisualConfig {
  objectFit: 'cover' | 'contain' | 'fill'
  objectPosition: string
  applyGradientOverlay: boolean
  gradientOverlay: string
  borderRadius: string

  // ⭐ NEW: Unified dimensions configuration
  dimensions: BannerDimensionsConfig
}
