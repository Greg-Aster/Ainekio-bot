/**
 * ===================================================================
 * BANNER CONFIGURATION - FIXED MOBILE NAVBAR SPACING
 * ===================================================================
 */

// Import siteConfig for background image resolution
import { siteConfig } from '../config/config'

// Import types from existing types.ts
import type {
  BannerAnimationConfig,
  BannerData,
  BannerDeterminationResult,
  BannerType,
  LinkPreviewInfo,
  PostBannerData,
} from './banners/types'

import { assistantBannerConfig } from './banners/assistant'
import { imageBannerConfig } from './banners/image'
import { noneBannerConfig } from './banners/none'
// Import banner configurations
import { standardBannerConfig } from './banners/standard'
import { timelineBannerConfig } from './banners/timeline'
import { videoBannerConfig } from './banners/video'

import { isAssistantBannerData } from './banners/assistant'
import { isImageBannerData } from './banners/image'
import { isNoneBannerData } from './banners/none'
import { isTimelineBannerData } from './banners/timeline'
// Import type guards
import { isVideoBannerData } from './banners/video'

// =====================================================================
// BACKGROUND IMAGE HELPERS - FIXED
// =====================================================================

export function getDynamicBackgroundImage(
  backgroundImage?: string | null,
): string | null {
  // 1. Check for explicit "none" or empty string
  if (backgroundImage === 'none' || backgroundImage === '') {
    return null
  }

  // 2. Use explicit backgroundImage prop if provided
  if (backgroundImage) {
    if (import.meta.env.DEV) {
    }
    return backgroundImage
  }

  // 3. Use imported siteConfig (primary method)
  if (siteConfig?.banner?.enable && siteConfig?.banner?.src) {
    if (import.meta.env.DEV) {
    }
    return siteConfig.banner.src
  }

  // 4. Fallback: Check window object for client-side compatibility
  if (
    typeof window !== 'undefined' &&
    (window as any).siteConfig?.banner?.enable &&
    (window as any).siteConfig?.banner?.src
  ) {
    if (import.meta.env.DEV) {
      console.log(
        'Using window.siteConfig background image:',
        (window as any).siteConfig.banner.src,
      )
    }
    return (window as any).siteConfig.banner.src
  }

  console.warn(
    'No background image found - check siteConfig.banner configuration',
  )
  return null
}

export function getShouldShowParallaxBackground(
  backgroundImage?: string | null,
): boolean {
  const currentBackgroundImage = getDynamicBackgroundImage(backgroundImage)
  const isParallaxEnabled = bannerConfig.parallax.enabled

  const shouldShow = !!(currentBackgroundImage && isParallaxEnabled)

  // Debug logging for development
  if (
    import.meta.env.DEV &&
    typeof window !== 'undefined' &&
    window.location.hostname === 'localhost'
  ) {
    console.log('Input backgroundImage prop:', backgroundImage)
    console.log('Resolved currentBackgroundImage:', currentBackgroundImage)
    console.log('Parallax enabled in config:', isParallaxEnabled)
    console.log('Should show parallax background:', shouldShow)
    console.log('siteConfig.banner:', siteConfig?.banner)
    console.log('================================')
  }

  return shouldShow
}

// =====================================================================
// RESTORED INTERFACES - BACK TO WORKING VERSION
// =====================================================================

/**
 * 🎯 ACTUAL BANNER DIMENSIONS - Only used by CSS
 */
export interface BannerDimensions {
  aspectRatio: string // 16:9 aspect ratio (critical)
  maxWidth: string // Max banner width (responsive)
  padding: string // Horizontal padding (responsive)
  borderRadius: string // Border radius
}

/**
 * 🎯 MAIN CONFIG - RESTORED WORKING VERSION
 */
export interface BannerConfig {
  // Banner type configs
  defaultBannerType: BannerType
  defaultBannerData: BannerData
  standardBannerConfig: typeof standardBannerConfig
  videoBannerConfig: typeof videoBannerConfig
  imageBannerConfig: typeof imageBannerConfig
  timelineBannerConfig: typeof timelineBannerConfig
  assistantBannerConfig: typeof assistantBannerConfig
  noneBannerConfig: typeof noneBannerConfig

  // Actual working configuration
  dimensions: BannerDimensions

  // WORKING: Layout values used by MainGridLayout.astro
  layout: {
    height: string
    mobileHeight?: string
    maxWidth: number
    mainContentOffset: string
  }

  // WORKING: Visual config used by existing code
  visual: {
    objectFit: string
    objectPosition: string
    applyGradientOverlay: boolean
    gradientOverlay: string
    borderRadius: string
  }

  // WORKING: Fallback configuration
  fallback: {
    enabled: boolean
    type: string
    value: string
  }

  // WORKING: Navbar spacing for different banner types
  navbar: {
    height: string
    spacing: {
      standard: string
      timeline: string
      video: string
      image: string
      assistant: string
      none: string
    }
    // ⭐ FIXED: Mobile portrait spacing now accounts for always-visible navbar
    mobileBannerGap?: string
    mobilePortraitSpacing: string
  }

  // 🎯 WORKING: The REAL overlap system - this controls banner overlap!
  panel: {
    top: {
      video: string
      image: string
      timeline: string
      assistant: string
      standard: string // ⭐ THIS IS YOUR BANNER OVERLAP CONTROL!
      none: string
    }
  }

  // WORKING: Parallax configuration
  parallax: {
    enabled: boolean
    scrollFactor: number
    easingFactor: number
  }

  // WORKING: Navigation configuration
  navigation?: {
    enabled: boolean
    showPositionIndicator: boolean
    showBannerTitles: boolean
    autoResumeDelay: number
    keyboardNavigation: boolean
    enabledForTypes: BannerType[]
    styling?: {
      buttonSize?: string
      indicatorSize?: string
      animationDuration?: string
    }
  }
}

/**
 * ===================================================================
 * MAIN CONFIGURATION - FIXED MOBILE NAVBAR SPACING
 * ===================================================================
 */
export const bannerConfig: BannerConfig = {
  // Default banner type
  defaultBannerType: 'standard',
  defaultBannerData: {} as any,

  // Banner type configurations
  standardBannerConfig,
  videoBannerConfig,
  imageBannerConfig,
  timelineBannerConfig,
  assistantBannerConfig,
  noneBannerConfig,

  // 🎯 FIXED: CSS dimensions system - NO MORE clamp() ISSUES
  dimensions: {
    aspectRatio: '56.25%', // 16:9 ratio (critical for your content)
    maxWidth: '100vw', // ✅ FIXED: Simple full width (was clamp issue)
    padding: '0', // ✅ FIXED: No padding (was clamp issue)
    borderRadius: '.5rem', // Standard Tailwind radius
  },

  // WORKING: Layout used by MainGridLayout.astro
  layout: {
    height: '80vh',
    mobileHeight: '50vh',
    maxWidth: 3840,
    mainContentOffset: '.5rem',
  },

  // WORKING: Visual config used by existing code
  visual: {
    objectFit: 'cover',
    objectPosition: 'center',
    applyGradientOverlay: true,
    gradientOverlay:
      'linear-gradient(to bottom, rgba(0,0,0,0.1), rgba(0,0,0,0.3))',
    borderRadius: '0.5rem',
  },

  // WORKING: Fallback configuration
  fallback: {
    enabled: true,
    type: 'gradient',
    value:
      'linear-gradient(135deg, oklch(0.6 0.2 var(--hue)), oklch(0.4 0.3 var(--hue)))',
  },

  // 🎯 FIXED: Navbar spacing - Mobile portrait now accounts for always-visible navbar
  navbar: {
    height: '5rem',
    spacing: {
      standard: '3rem', // ✅ Desktop spacing
      timeline: '5.5rem', // ✅ Desktop spacing
      video: '5.5rem', // ✅ Desktop spacing
      image: '4rem', // ✅ Desktop spacing
      assistant: '5.5rem', // ✅ Desktop spacing
      none: '-8rem', // ✅ Desktop spacing
    },
    // No extra mobile banner offset: navbar stays in normal flow above the banner
    mobileBannerGap: '2.75rem',
    mobilePortraitSpacing: '0.75rem',
  },

  // 🎯 FIXED: THE REAL OVERLAP SYSTEM - NO MORE clamp() ISSUES
  panel: {
    top: {
      video: '-0.5rem', // ✅ WORKING VALUE
      image: '-0.5rem', // ✅ WORKING VALUE
      timeline: '-0.5rem', // ✅ WORKING VALUE
      assistant: '-0.5rem', // ✅ WORKING VALUE
      standard: '-2rem', // ✅ Reduced overlap for better content visibility
      none: '12rem', // ✅ WORKING VALUE
    },
  },

  // WORKING: Parallax configuration - ENABLED BY DEFAULT
  parallax: {
    enabled: true,
    scrollFactor: -0.02,
    easingFactor: 0.1,
  },

  // WORKING: Navigation configuration
  navigation: {
    enabled: true,
    showPositionIndicator: true,
    showBannerTitles: true,
    autoResumeDelay: 5000,
    keyboardNavigation: true,
    enabledForTypes: ['standard', 'image', 'video'] as BannerType[],
    styling: {
      buttonSize: '2.75rem',
      indicatorSize: '0.4375rem',
      animationDuration: '0.3s',
    },
  },
}

// =====================================================================
// RESTORED HELPER FUNCTIONS - WORKING VERSION
// =====================================================================

export function isFullscreenModeActive(): boolean {
  if (typeof window === 'undefined' || typeof localStorage === 'undefined') {
    return false
  }
  return localStorage.getItem('fullscreenBannerOverride') === 'true'
}

export function getBannerDataFromPost(post: any): PostBannerData | null {
  if (!post?.data) return null

  return {
    bannerLink: post.data.bannerLink || '',
    customAvatar: post.data.avatarImage || '',
    customName: post.data.authorName || '',
    customBio: post.data.authorBio || '',
    slug: post.slug || '',
    // `showImageOnPost` only hides the inline cover image inside the article body.
    // It should not disable the top banner or the site's fallback banner system.
    wantsNoDefaultBanner: false,
  }
}

export function determineBannerType(
  post: any,
  postData: PostBannerData | null,
): BannerDeterminationResult {
  // Check for post-specific banners
  const hasPostTimelineBanner =
    post?.data?.bannerType === 'timeline' && post?.data?.bannerData?.category
  const hasPostVideoBanner =
    post?.data?.bannerType === 'video' && post?.data?.bannerData?.videoId
  const hasPostAssistantBanner = post?.data?.bannerType === 'assistant'
  const hasPostImageBanner =
    !postData?.wantsNoDefaultBanner &&
    (post?.data?.image ||
      (post?.data?.bannerType === 'image' &&
        post?.data?.bannerData?.imageUrl)) &&
    !hasPostVideoBanner &&
    !hasPostTimelineBanner &&
    !hasPostAssistantBanner

  const hasPostBanner =
    hasPostVideoBanner ||
    hasPostImageBanner ||
    hasPostTimelineBanner ||
    hasPostAssistantBanner

  // Check for default banners
  const useDefaultVideo =
    !hasPostBanner &&
    !postData?.wantsNoDefaultBanner &&
    bannerConfig.defaultBannerType === 'video' &&
    isVideoBannerData(bannerConfig.defaultBannerData)
  const useDefaultImage =
    !hasPostBanner &&
    !postData?.wantsNoDefaultBanner &&
    bannerConfig.defaultBannerType === 'image' &&
    isImageBannerData(bannerConfig.defaultBannerData)
  const useDefaultTimeline =
    !hasPostBanner &&
    !postData?.wantsNoDefaultBanner &&
    bannerConfig.defaultBannerType === 'timeline' &&
    isTimelineBannerData(bannerConfig.defaultBannerData)
  const useDefaultAssistant =
    !hasPostBanner &&
    !postData?.wantsNoDefaultBanner &&
    bannerConfig.defaultBannerType === 'assistant' &&
    isAssistantBannerData(bannerConfig.defaultBannerData)
  const useDefaultStandard =
    !hasPostBanner &&
    !postData?.wantsNoDefaultBanner &&
    (bannerConfig.defaultBannerType === 'standard' ||
      (!useDefaultVideo &&
        !useDefaultImage &&
        !useDefaultTimeline &&
        !useDefaultAssistant))

  // Determine banner flags
  const hasTimelineBanner = hasPostTimelineBanner || useDefaultTimeline
  const hasVideoBanner = hasPostVideoBanner || useDefaultVideo
  const hasImageBanner = hasPostImageBanner || useDefaultImage
  const hasAssistantBanner = hasPostAssistantBanner || useDefaultAssistant
  const hasStandardBanner = useDefaultStandard

  const currentBannerType: BannerType = hasVideoBanner
    ? 'video'
    : hasImageBanner
      ? 'image'
      : hasTimelineBanner
        ? 'timeline'
        : hasAssistantBanner
          ? 'assistant'
          : hasStandardBanner
            ? 'standard'
            : 'none'

  return {
    hasTimelineBanner,
    hasVideoBanner,
    hasImageBanner,
    hasAssistantBanner,
    hasStandardBanner,
    hasPostBanner,
    isStandardPage: !hasPostBanner,
    currentBannerType,
  }
}

export function getBannerDataSources(
  bannerType: BannerDeterminationResult,
  post: any,
) {
  const {
    hasTimelineBanner,
    hasVideoBanner,
    hasImageBanner,
    hasAssistantBanner,
  } = bannerType

  let resolvedImageBannerData: any = null
  if (hasImageBanner) {
    if (post?.data?.bannerType === 'image') {
      const imageUrl = post.data.bannerData?.imageUrl || post.data.image
      if (typeof imageUrl === 'string') {
        resolvedImageBannerData = { imageUrl: imageUrl }
      } else {
        console.warn(
          'Banner config: Post-specific image banner lacks a valid imageUrl. Falling back to default.',
        )
        resolvedImageBannerData = bannerConfig.imageBannerConfig.data
      }
    } else {
      if (isImageBannerData(bannerConfig.imageBannerConfig.data)) {
        resolvedImageBannerData = bannerConfig.imageBannerConfig.data
      } else {
        console.warn(
          'Banner config: Mismatch in default image banner data type. Falling back to imageBannerConfig.data.',
        )
        resolvedImageBannerData = bannerConfig.imageBannerConfig.data
      }
    }
  }

  return {
    videoBannerData:
      hasVideoBanner && post?.data?.bannerType === 'video'
        ? post.data.bannerData
        : hasVideoBanner
          ? bannerConfig.defaultBannerData
          : null,

    imageBannerData: resolvedImageBannerData,

    timelineBannerData:
      hasTimelineBanner && post?.data?.bannerType === 'timeline'
        ? post.data.bannerData
        : hasTimelineBanner
          ? bannerConfig.defaultBannerData
          : null,

    assistantBannerData:
      hasAssistantBanner && post?.data?.bannerType === 'assistant'
        ? post.data.bannerData
        : hasAssistantBanner
          ? bannerConfig.defaultBannerData
          : null,
  }
}

/**
 * 🎯 MAIN API: Banner configuration determination - CLEANED VERSION
 */
export function determineBannerConfiguration(
  post: any,
  pageType: string,
  defaultBannerLink = '',
) {
  // ⭐ NEW: Check user's saved banner type preference
  if (import.meta.env.DEV) {
    console.log(
      '🏗️ Banner config starting. Default type:',
      bannerConfig.defaultBannerType,
    )
  }
  if (
    typeof window !== 'undefined' &&
    localStorage.getItem('defaultBannerType')
  ) {
    const savedType = localStorage.getItem('defaultBannerType')
    if (import.meta.env.DEV) {
    }
    bannerConfig.defaultBannerType = savedType as BannerType
    if (import.meta.env.DEV) {
    }
  } else if (import.meta.env.DEV) {
  }

  if (isFullscreenModeActive()) {
    return {
      postData: getBannerDataFromPost(post),
      bannerType: {
        hasTimelineBanner: false,
        hasVideoBanner: false,
        hasImageBanner: false,
        hasAssistantBanner: false,
        hasStandardBanner: false,
        hasPostBanner: false,
        isStandardPage: false,
        currentBannerType: 'none' as BannerType,
      },
      bannerDataSources: {
        videoBannerData: null,
        imageBannerData: null,
        timelineBannerData: null,
        assistantBannerData: null,
      },
      layout: {
        mainPanelTop: bannerConfig.panel.top.none,
        navbarSpacing: '0rem',
        bannerHeight: '0',
        bannerOverlap: '0',
        dynamicOverlap: '0',
        mainContentOffset: bannerConfig.layout.mainContentOffset,
      },
      finalBannerLink: '',
      currentBannerType: 'none' as BannerType,
    }
  }

  const postData = getBannerDataFromPost(post)
  const bannerType = determineBannerType(post, postData)
  const bannerDataSources = getBannerDataSources(bannerType, post)

  // 🎯 THE REAL WORKING VALUES - RESTORED
  const mainPanelTop = getPanelTopPosition(bannerType.currentBannerType)

  // ⭐ SIMPLIFIED: Always use regular spacing - CSS handles mobile portrait now
  const navbarSpacing =
    bannerConfig.navbar.spacing[bannerType.currentBannerType]

  const bannerHeight = bannerConfig.layout.height
  const mainContentOffset = bannerConfig.layout.mainContentOffset

  const finalBannerLink = postData?.bannerLink || defaultBannerLink

  return {
    postData,
    bannerType,
    bannerDataSources,
    layout: {
      mainPanelTop, // 🎯 THIS CONTROLS OVERLAP! (RESTORED)
      navbarSpacing, // ⭐ SIMPLIFIED - CSS handles mobile portrait
      bannerHeight,
      bannerHeightMobile:
        bannerConfig.layout.mobileHeight ?? bannerConfig.layout.height,
      bannerOverlap: '0', // Removed unused value
      dynamicOverlap: '0', // Removed unused value
      mainContentOffset,
    },
    finalBannerLink,
    currentBannerType: bannerType.currentBannerType,
  }
}

// =====================================================================
// RESTORED UTILITY FUNCTIONS - KEPT ONLY WORKING ONES
// =====================================================================

export function getResponsiveBannerDimensions(): { height: string } {
  return {
    height: bannerConfig.layout.height,
  }
}

export function getFallbackBannerCSS(): string {
  if (!bannerConfig.fallback.enabled) return ''
  return bannerConfig.fallback.type === 'gradient'
    ? bannerConfig.fallback.value
    : `${bannerConfig.fallback.value}`
}

export function getBannerAnimationSettings(): BannerAnimationConfig {
  return bannerConfig.standardBannerConfig.getBannerAnimationSettings()
}

// 🎯 THE FUNCTION THAT CONTROLS OVERLAP! - RESTORED
export function getPanelTopPosition(bannerType: BannerType): string {
  switch (bannerType) {
    case 'video':
      return bannerConfig.panel.top.video
    case 'image':
      return bannerConfig.panel.top.image
    case 'timeline':
      return bannerConfig.panel.top.timeline
    case 'assistant':
      return bannerConfig.panel.top.assistant
    case 'none':
      return bannerConfig.panel.top.none
    default:
      return bannerConfig.panel.top.standard // ⭐ THIS IS YOUR OVERLAP!
  }
}

export function getPageSpecificOverlap(pageType: string): string {
  // This function is no longer used but kept for compatibility
  return '0'
}

export function getNavbarHeight(): string {
  return bannerConfig.navbar.height
}

export function getMainContentOffset(): string {
  return bannerConfig.layout.mainContentOffset
}

export function getBannerLink(index: number): string | null {
  return bannerConfig.standardBannerConfig.getBannerLink(index)
}

export function hasAnyBannerLinks(): boolean {
  return bannerConfig.standardBannerConfig.hasAnyBannerLinks()
}

export function getLinkPreviewData(url: string): LinkPreviewInfo {
  return bannerConfig.standardBannerConfig.getLinkPreviewData(url)
}

export function getIconSVG(iconName: string): string {
  return bannerConfig.standardBannerConfig.getIconSVG(iconName)
}

// =====================================================================
// DEPRECATED FUNCTIONS - KEPT FOR BACKWARDS COMPATIBILITY
// =====================================================================

/** @deprecated Use getPanelTopPosition instead */
export function calculateBannerLayout() {
  console.warn(
    'calculateBannerLayout is deprecated, using working system instead',
  )
}

// Re-export type guards and configurations
export {
  isVideoBannerData,
  isImageBannerData,
  isTimelineBannerData,
  isAssistantBannerData,
  isNoneBannerData,
}

export function isStandardBannerData(data: any): data is any {
  return data && typeof data === 'object' && Object.keys(data).length === 0
}

export {
  standardBannerConfig,
  videoBannerConfig,
  imageBannerConfig,
  timelineBannerConfig,
  assistantBannerConfig,
  noneBannerConfig,
}

// Re-export types
export type {
  BannerType,
  BannerData,
  BannerDeterminationResult,
  PostBannerData,
  LinkPreviewInfo,
  BannerAnimationConfig,
} from './banners/types'

(bannerConfig as any).panel ??= {}
(bannerConfig as any).panel.top ??= {}
(bannerConfig as any).panel.top.mobilePortrait = '-2rem'
