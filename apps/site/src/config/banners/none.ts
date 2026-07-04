/**
 * ===================================================================
 * NONE BANNER CONFIGURATION - NO BANNER DISPLAY
 * ===================================================================
 *
 * This file manages the "none" banner type configuration for pages that
 * should not display any banner content. It provides placeholder styling
 * and layout adjustments for banner-less pages while maintaining
 * consistent spacing and layout structure.
 *
 * FEATURES:
 * - Clean layout without banner elements
 * - Consistent spacing and positioning for banner-less pages
 * - Optional placeholder space for layout consistency
 * - Seamless integration with site navigation and content
 * - Responsive adjustments for different screen sizes
 *
 * USAGE:
 * - Automatically used when defaultBannerType is set to 'none'
 * - Can be applied to specific posts via frontmatter: bannerType: "none"
 * - Use isNoneBannerData() type guard for safe type checking
 * - Configure placeholder height if consistent spacing is needed
 *
 * MAINTENANCE NOTES:
 * - Adjust placeholder height if site layout requires consistent spacing
 * - Modify spacing settings to align with overall site design
 * - Update fallback styling to match site theme
 * - Consider accessibility implications of banner-less layouts
 * ===================================================================
 */

import type { NoneBannerData } from './types'

// =====================================================================
// NONE BANNER DATA CONFIGURATION
// =====================================================================

/**
 * None banner configuration object
 * Empty configuration as no banner content should be displayed
 */
export const noneBannerData: NoneBannerData = {
  // No additional data needed for none banner - used when no banner should be displayed
}

// =====================================================================
// NONE BANNER LAYOUT CONFIGURATION
// =====================================================================

/**
 * Layout configuration for pages without banners
 * Controls spacing and positioning when no banner is present
 */
export const noneBannerLayout = {
  // Placeholder settings
  showPlaceholder: false, // Whether to show a placeholder space
  placeholderHeight: {
    desktop: '0', // No placeholder height on desktop
    mobile: '0', // No placeholder height on mobile
  },

  // Alternative: If you want consistent spacing, use these values
  consistentSpacing: {
    enabled: false, // Enable consistent spacing mode
    height: {
      desktop: '4.5rem', // Match navbar height for consistency
      mobile: '3.5rem', // Match mobile navbar height
    },
  },

  // Content positioning
  contentStartPosition: {
    desktop: '0', // Content starts immediately after navbar
    mobile: '0', // Content starts immediately after navbar on mobile
  },

  // Margin adjustments for better visual hierarchy
  topMargin: {
    desktop: '2rem', // Add some breathing room on desktop
    mobile: '1rem', // Add some breathing room on mobile
  },
}

/**
 * Visual styling for none banner pages
 * Provides minimal styling for clean, banner-less layouts
 */
export const noneBannerVisualConfig = {
  // Background options (if any visual element is needed)
  showBackgroundGradient: false, // Show subtle gradient where banner would be
  backgroundGradient: 'linear-gradient(135deg, transparent, rgba(0,0,0,0.02))',

  // Divider options
  showDivider: false, // Show divider line where banner would be
  dividerColor: 'rgba(0,0,0,0.1)', // Color of divider if shown
  dividerThickness: '1px', // Thickness of divider

  // Shadow options for subtle depth
  showShadow: false, // Add subtle shadow for depth
  shadowColor: 'rgba(0,0,0,0.05)', // Shadow color
  shadowSize: '0 2px 4px', // Shadow size and blur
}

/**
 * None banner responsive configuration
 * Handles different screen sizes and orientations
 */
export const noneBannerResponsiveConfig = {
  // Breakpoints for different behavior
  breakpoints: {
    mobile: 768, // Mobile breakpoint (px)
    tablet: 1024, // Tablet breakpoint (px)
    desktop: 1200, // Desktop breakpoint (px)
  },

  // Responsive adjustments
  adjustments: {
    mobile: {
      reduceSpacing: true, // Reduce spacing on mobile
      spacingReduction: '0.5rem', // Amount to reduce spacing
    },
    tablet: {
      moderateSpacing: true, // Use moderate spacing on tablet
      spacingMultiplier: 0.75, // Multiply standard spacing by this factor
    },
    desktop: {
      normalSpacing: true, // Use normal spacing on desktop
    },
  },
}

// =====================================================================
// HELPER FUNCTIONS
// =====================================================================

/**
 * Get none banner layout styles
 * Returns CSS styles for banner-less page layout
 *
 * @param options - Optional configuration overrides
 * @returns CSS style object
 */
export function getNoneBannerStyles(options?: {
  showPlaceholder?: boolean
  consistentSpacing?: boolean
  isMobile?: boolean
}): Record<string, string> {
  const styles: Record<string, string> = {}
  const isMobile = options?.isMobile || false

  // Handle placeholder space if requested
  if (options?.showPlaceholder || noneBannerLayout.showPlaceholder) {
    const height = isMobile
      ? noneBannerLayout.placeholderHeight.mobile
      : noneBannerLayout.placeholderHeight.desktop
    styles.height = height
    styles.minHeight = height
  }

  // Handle consistent spacing mode
  if (
    options?.consistentSpacing ||
    noneBannerLayout.consistentSpacing.enabled
  ) {
    const height = isMobile
      ? noneBannerLayout.consistentSpacing.height.mobile
      : noneBannerLayout.consistentSpacing.height.desktop
    styles.paddingTop = height
  }

  // Add top margin for visual hierarchy
  const topMargin = isMobile
    ? noneBannerLayout.topMargin.mobile
    : noneBannerLayout.topMargin.desktop

  if (topMargin !== '0') {
    styles.marginTop = topMargin
  }

  // Add background gradient if enabled
  if (noneBannerVisualConfig.showBackgroundGradient) {
    styles.background = noneBannerVisualConfig.backgroundGradient
  }

  // Add divider if enabled
  if (noneBannerVisualConfig.showDivider) {
    styles.borderBottom = `${noneBannerVisualConfig.dividerThickness} solid ${noneBannerVisualConfig.dividerColor}`
  }

  // Add shadow if enabled
  if (noneBannerVisualConfig.showShadow) {
    styles.boxShadow = `${noneBannerVisualConfig.shadowSize} ${noneBannerVisualConfig.shadowColor}`
  }

  return styles
}

/**
 * Get content positioning for none banner pages
 * Returns CSS values for positioning main content without banner
 *
 * @param isMobile - Whether to get mobile positioning
 * @returns Object with positioning CSS values
 */
export function getNoneBannerContentPosition(isMobile = false): {
  top: string
  marginTop: string
  paddingTop: string
} {
  const device = isMobile ? 'mobile' : 'desktop'

  return {
    top: noneBannerLayout.contentStartPosition[device],
    marginTop: noneBannerLayout.topMargin[device],
    paddingTop: noneBannerLayout.consistentSpacing.enabled
      ? noneBannerLayout.consistentSpacing.height[device]
      : '0',
  }
}

/**
 * Check if consistent spacing should be applied
 * Determines if none banner should maintain consistent spacing with other pages
 *
 * @param pageContext - Optional page context information
 * @returns True if consistent spacing should be applied
 */
export function shouldApplyConsistentSpacing(pageContext?: {
  hasOtherBannersOnSite?: boolean
  userPreference?: 'consistent' | 'minimal'
  layoutMode?: 'fixed' | 'fluid'
}): boolean {
  // Apply consistent spacing if other pages have banners
  if (pageContext?.hasOtherBannersOnSite) {
    return true
  }

  // Apply based on user preference
  if (pageContext?.userPreference === 'consistent') {
    return true
  }

  // Apply for fixed layouts
  if (pageContext?.layoutMode === 'fixed') {
    return true
  }

  // Default to configuration setting
  return noneBannerLayout.consistentSpacing.enabled
}

/**
 * Validate none banner configuration
 * Ensures none banner settings are properly configured
 *
 * @param config - None banner configuration to validate
 * @returns Validation result with any warnings or errors
 */
export function validateNoneBannerConfig(config: NoneBannerData): {
  isValid: boolean
  warnings: string[]
  errors: string[]
} {
  const warnings: string[] = []
  const errors: string[] = []

  // Check if config is properly empty (none banner should have no data)
  const configKeys = Object.keys(config)
  if (configKeys.length > 0) {
    warnings.push(
      'None banner configuration should be empty. Unexpected properties found: ' +
        configKeys.join(', '),
    )
  }

  // Validate layout configuration consistency
  if (
    noneBannerLayout.showPlaceholder &&
    noneBannerLayout.consistentSpacing.enabled
  ) {
    warnings.push(
      'Both placeholder and consistent spacing are enabled. This may cause double spacing.',
    )
  }

  // Check placeholder height values
  if (noneBannerLayout.showPlaceholder) {
    const desktopHeight = noneBannerLayout.placeholderHeight.desktop
    const mobileHeight = noneBannerLayout.placeholderHeight.mobile

    if (desktopHeight === '0' && mobileHeight === '0') {
      warnings.push(
        'Placeholder is enabled but heights are set to 0. Consider disabling placeholder instead.',
      )
    }
  }

  return {
    isValid: errors.length === 0,
    warnings,
    errors,
  }
}

/**
 * Get responsive adjustments for none banner
 * Returns responsive adjustments based on screen size
 *
 * @param screenWidth - Current screen width in pixels
 * @returns Responsive adjustment object
 */
export function getNoneBannerResponsiveAdjustments(screenWidth: number): {
  spacingMultiplier: number
  shouldReduceSpacing: boolean
  deviceType: 'mobile' | 'tablet' | 'desktop'
} {
  const { breakpoints, adjustments } = noneBannerResponsiveConfig

  if (screenWidth < breakpoints.mobile) {
    return {
      spacingMultiplier: adjustments.mobile.reduceSpacing ? 0.5 : 1,
      shouldReduceSpacing: adjustments.mobile.reduceSpacing,
      deviceType: 'mobile',
    }
  } else if (screenWidth < breakpoints.tablet) {
    return {
      spacingMultiplier: adjustments.tablet.spacingMultiplier || 1,
      shouldReduceSpacing: false,
      deviceType: 'tablet',
    }
  } else {
    return {
      spacingMultiplier: 1,
      shouldReduceSpacing: false,
      deviceType: 'desktop',
    }
  }
}

// =====================================================================
// TYPE GUARDS
// =====================================================================

/**
 * Check if data is valid NoneBannerData
 * Used when no banner should be displayed - data should be empty
 *
 * @param data - Data to check
 * @returns True if data is valid NoneBannerData
 */
export function isNoneBannerData(data: any): data is NoneBannerData {
  return data && typeof data === 'object' && Object.keys(data).length === 0
}

// =====================================================================
// EXPORT CONFIGURATION OBJECT
// =====================================================================

/**
 * Complete none banner configuration
 * Combines all settings, data, and helper functions
 */
export const noneBannerConfig = {
  data: noneBannerData,
  layout: noneBannerLayout,
  visual: noneBannerVisualConfig,
  responsive: noneBannerResponsiveConfig,

  // Helper functions
  getNoneBannerStyles,
  getNoneBannerContentPosition,
  shouldApplyConsistentSpacing,
  validateNoneBannerConfig,
  getNoneBannerResponsiveAdjustments,
  isNoneBannerData,
}
