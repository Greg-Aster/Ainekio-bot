/**
 * ===================================================================
 * BANNER CONFIGURATIONS INDEX - CENTRALIZED EXPORTS
 * ===================================================================
 *
 * This file provides centralized exports for all banner configuration modules,
 * making it easier to import banner configurations throughout the application.
 * It serves as the main entry point for the banner system.
 *
 * ORGANIZATION:
 * - Type definitions and interfaces
 * - Individual banner type configurations
 * - Helper functions and utilities
 * - Type guards for safe type checking
 * - Validation functions
 *
 * USAGE:
 * - Import specific configurations: import { standardBannerConfig } from '@/config/banners'
 * - Import types: import type { BannerType } from '@/config/banners'
 * - Import utilities: import { isVideoBannerData } from '@/config/banners'
 * - Import everything: import * as BannerConfigs from '@/config/banners'
 *
 * MAINTENANCE NOTES:
 * - Add new banner type exports when creating new banner modules
 * - Keep exports organized by category for better discoverability
 * - Update re-exports when banner APIs change
 * - Maintain consistent naming conventions
 * ===================================================================
 */

// =====================================================================
// TYPE DEFINITIONS AND INTERFACES
// =====================================================================

// Export all type definitions for external use
export type {
  // Core banner types
  BannerType,
  BannerData,
  // Individual banner data types
  StandardBannerData,
  VideoBannerData,
  ImageBannerData,
  TimelineBannerData,
  AssistantBannerData,
  NoneBannerData,
  // Configuration interfaces
  BannerAnimationConfig,
  BannerLayoutConfig,
  BannerVisualConfig,
  BannerFallbackConfig,
  BannerNavbarConfig,
  BannerPanelConfig,
  BannerParallaxConfig,
  // Helper types
  BannerDeterminationResult,
  PostBannerData,
  LinkPreviewInfo,
} from './types'

// =====================================================================
// BANNER TYPE CONFIGURATIONS
// =====================================================================

// Export complete banner configurations
export { standardBannerConfig } from './standard'
export { videoBannerConfig } from './video'
export { imageBannerConfig } from './image'
export { timelineBannerConfig } from './timeline'
export { assistantBannerConfig } from './assistant'
export { noneBannerConfig } from './none'

// Export individual banner data objects for direct access
export { standardBannerData } from './standard'
export { videoBannerData } from './video'
export { imageBannerData } from './image'
export { timelineBannerData } from './timeline'
export { assistantBannerData } from './assistant'
export { noneBannerData } from './none'

// =====================================================================
// STANDARD BANNER SPECIFIC EXPORTS
// =====================================================================

// Export standard banner assets and configuration
export {
  bannerList,
  bannerLinks,
  defaultBanner,
  linkPreviewData,
  animationConfig,
  iconSVGs,
} from './standard'

// Export standard banner helper functions
export {
  getBannerAnimationSettings,
  getBannerLink,
  hasAnyBannerLinks,
  getLinkPreviewData,
  getIconSVG,
  validateStandardBannerConfig,
} from './standard'

// =====================================================================
// VIDEO BANNER SPECIFIC EXPORTS
// =====================================================================

// Export video banner configuration objects
export {
  videoParameters,
  qualityPreferences,
  aspectRatioConfig,
  videoFallbackConfig,
  videoLoadingConfig,
} from './video'

// Export video banner helper functions
export {
  getVideoEmbedUrl,
  extractVideoId,
  validateVideoBannerConfig,
  getVideoThumbnail,
  getVideoIframeAttributes,
} from './video'

// =====================================================================
// IMAGE BANNER SPECIFIC EXPORTS
// =====================================================================

// Export image banner configuration objects
export {
  imageOptimizationConfig,
  responsiveBreakpoints,
  imageDisplayConfig,
  imageFallbackConfig,
  imageLoadingConfig,
} from './image'

// Export image banner helper functions
export {
  getOptimizedImageUrl,
  getResponsiveImageSources,
  validateImageBannerConfig,
  getImageAttributes,
  isExternalImage,
  getImagePlaceholder,
} from './image'

// =====================================================================
// TIMELINE BANNER SPECIFIC EXPORTS
// =====================================================================

// Export timeline banner configuration objects
export {
  timelineBannerViewConfig,
  timelineBannerLayout,
  timelineBannerInteraction,
  timelineBannerEraConfig,
  timelineBannerCategories,
} from './timeline'

// Export timeline banner helper functions
export {
  getTimelineBannerConfig,
  validateTimelineBannerConfig,
  getEraForTimelineRange,
  getTimelineBannerStyles,
  getTimelineBannerCategory,
} from './timeline'

// =====================================================================
// ASSISTANT BANNER SPECIFIC EXPORTS
// =====================================================================

// Export assistant banner configuration objects
export {
  assistantPersonality,
  assistantGreetings,
  assistantBannerLayout,
  assistantBannerInteraction,
  assistantQuickActions,
  contextualActions,
  assistantBannerStyling,
} from './assistant'

// Export assistant banner helper functions
export {
  getContextualGreeting,
  getContextualQuickActions,
  validateAssistantBannerConfig,
  getAssistantBannerStyles,
  getAssistantAvatar,
} from './assistant'

// =====================================================================
// NONE BANNER SPECIFIC EXPORTS
// =====================================================================

// Export none banner configuration objects
export {
  noneBannerLayout,
  noneBannerVisualConfig,
  noneBannerResponsiveConfig,
} from './none'

// Export none banner helper functions
export {
  getNoneBannerStyles,
  getNoneBannerContentPosition,
  shouldApplyConsistentSpacing,
  validateNoneBannerConfig,
  getNoneBannerResponsiveAdjustments,
} from './none'

// =====================================================================
// TYPE GUARDS AND VALIDATION
// =====================================================================

// Export type guard functions for safe type checking
export { isVideoBannerData } from './video'
export { isImageBannerData } from './image'
export { isTimelineBannerData } from './timeline'
export { isAssistantBannerData } from './assistant'
export { isNoneBannerData } from './none'

// =====================================================================
// COLLECTION OBJECTS FOR CONVENIENCE
// =====================================================================

/**
 * Collection of all banner configurations for easy access
 * Useful when you need to iterate over all banner types or access them dynamically
 */
export const allBannerConfigs = {
  standard: standardBannerConfig,
  video: videoBannerConfig,
  image: imageBannerConfig,
  timeline: timelineBannerConfig,
  assistant: assistantBannerConfig,
  none: noneBannerConfig,
} as const

/**
 * Collection of all banner data objects for easy access
 * Useful for accessing raw banner data without full configuration
 */
export const allBannerData = {
  standard: standardBannerData,
  video: videoBannerData,
  image: imageBannerData,
  timeline: timelineBannerData,
  assistant: assistantBannerData,
  none: noneBannerData,
} as const

/**
 * Collection of all type guard functions for easy access
 * Useful for dynamic type checking based on banner type strings
 */
export const bannerTypeGuards = {
  isVideoBannerData,
  isImageBannerData,
  isTimelineBannerData,
  isAssistantBannerData,
  isNoneBannerData,
} as const

/**
 * Collection of all validation functions for easy access
 * Useful for validating banner configurations programmatically
 */
export const bannerValidators = {
  validateStandardBannerConfig,
  validateVideoBannerConfig,
  validateImageBannerConfig,
  validateTimelineBannerConfig,
  validateAssistantBannerConfig,
  validateNoneBannerConfig,
} as const

// =====================================================================
// UTILITY FUNCTIONS
// =====================================================================

/**
 * Get banner configuration by type string
 * Dynamically returns the appropriate banner configuration
 *
 * @param bannerType - Banner type string
 * @returns Banner configuration object or null if invalid type
 */
export function getBannerConfigByType(bannerType: string) {
  switch (bannerType) {
    case 'standard':
      return standardBannerConfig
    case 'video':
      return videoBannerConfig
    case 'image':
      return imageBannerConfig
    case 'timeline':
      return timelineBannerConfig
    case 'assistant':
      return assistantBannerConfig
    case 'none':
      return noneBannerConfig
    default:
      return null
  }
}

/**
 * Get banner data by type string
 * Dynamically returns the appropriate banner data
 *
 * @param bannerType - Banner type string
 * @returns Banner data object or null if invalid type
 */
export function getBannerDataByType(bannerType: string) {
  switch (bannerType) {
    case 'standard':
      return standardBannerData
    case 'video':
      return videoBannerData
    case 'image':
      return imageBannerData
    case 'timeline':
      return timelineBannerData
    case 'assistant':
      return assistantBannerData
    case 'none':
      return noneBannerData
    default:
      return null
  }
}

/**
 * Get type guard function by banner type string
 * Dynamically returns the appropriate type guard function
 *
 * @param bannerType - Banner type string
 * @returns Type guard function or null if invalid type
 */
export function getTypeGuardByBannerType(bannerType: string) {
  switch (bannerType) {
    case 'video':
      return isVideoBannerData
    case 'image':
      return isImageBannerData
    case 'timeline':
      return isTimelineBannerData
    case 'assistant':
      return isAssistantBannerData
    case 'none':
      return isNoneBannerData
    case 'standard':
      // Standard banner data is just an empty object, so we can check for that
      return (data: any) =>
        data && typeof data === 'object' && Object.keys(data).length === 0
    default:
      return null
  }
}

/**
 * Get all available banner types
 * Returns array of all supported banner type strings
 *
 * @returns Array of banner type strings
 */
export function getAllBannerTypes(): string[] {
  return ['standard', 'video', 'image', 'timeline', 'assistant', 'none']
}

/**
 * Check if banner type is valid
 * Validates that a string is a supported banner type
 *
 * @param bannerType - Banner type string to validate
 * @returns True if banner type is valid
 */
export function isValidBannerType(
  bannerType: string,
): bannerType is keyof typeof allBannerConfigs {
  return getAllBannerTypes().includes(bannerType)
}

/**
 * Validate banner data for given type
 * Dynamically validates banner data using appropriate validator
 *
 * @param bannerType - Banner type string
 * @param data - Banner data to validate
 * @returns Validation result or null if invalid banner type
 */
export function validateBannerDataByType(bannerType: string, data: any) {
  switch (bannerType) {
    case 'standard':
      return validateStandardBannerConfig(data)
    case 'video':
      return validateVideoBannerConfig(data)
    case 'image':
      return validateImageBannerConfig(data)
    case 'timeline':
      return validateTimelineBannerConfig(data)
    case 'assistant':
      return validateAssistantBannerConfig(data)
    case 'none':
      return validateNoneBannerConfig(data)
    default:
      return null
  }
}
