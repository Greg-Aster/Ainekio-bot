/**
 * ===================================================================
 * TIMELINE BANNER CONFIGURATION - INTERACTIVE TIMELINE DISPLAYS
 * ===================================================================
 *
 * This file manages interactive timeline banner functionality for displaying
 * dynamic timeline content as engaging banner presentations. It integrates
 * with the main timeline system and provides configuration for timeline
 * visualization, era navigation, and interactive timeline controls.
 *
 * FEATURES:
 * - Interactive timeline navigation and zoom controls
 * - Era-based timeline visualization with custom backgrounds
 * - Dynamic timeline data integration
 * - Responsive timeline display for different screen sizes
 * - Customizable timeline categories and date ranges
 * - Integration with main timeline configuration system
 *
 * USAGE:
 * - Set timelineBannerData.category to filter timeline events
 * - Configure startYear and endYear to focus on specific time periods
 * - Use isTimelineBannerData() type guard for safe type checking
 * - Customize timeline appearance with background images and styling
 *
 * MAINTENANCE NOTES:
 * - Update timeline categories to match your content structure
 * - Modify era configurations to align with your timeline periods
 * - Adjust visualization settings for optimal user experience
 * - Configure background images for different eras and categories
 * ===================================================================
 */

// Import timeline configuration utilities
import type {
  EraConfig,
  EraConfigMap,
  TimelineEvent,
  TimelineViewConfig,
} from '../timelineconfig'
import {
  defaultEraConfig,
  defaultTimelineViewConfig,
  extractEraConfig,
  getEraClasses,
  getEraDisplayName,
  getEraFromYear,
  getTimelineStatistics,
} from '../timelineconfig'
import type { TimelineBannerData } from './types'

// =====================================================================
// TIMELINE BANNER DATA CONFIGURATION
// =====================================================================

/**
 * Default timeline banner configuration
 * Set category and date ranges to customize timeline display
 *
 * CATEGORY OPTIONS:
 * - Use specific categories to filter timeline events (e.g., "MEGA MEAL", "TECH", "HISTORY")
 * - Leave empty or use "ALL" to show all timeline events
 * - Categories should match those defined in your timeline events
 *
 * DATE RANGE OPTIONS:
 * - startYear/endYear: Focus timeline on specific time period
 * - Leave undefined to show entire timeline range
 * - Use era boundaries for era-specific timelines
 */
export const timelineBannerData: TimelineBannerData = {
  category: 'MEGA MEAL', // Required for timeline banner
  title: 'Site Timeline', // Optional display title
  startYear: 1, // Optional start year
  endYear: 50000, // Optional end year
  background: '/posts/timeline/universe.png', // Optional background image
  compact: false, // Optional compact display mode
  // height: "70vh"                 // Optional custom height
}

// =====================================================================
// TIMELINE DISPLAY CONFIGURATION
// =====================================================================

/**
 * Timeline visualization settings for banner display
 * Extended from default timeline config with banner-specific options
 */
export const timelineBannerViewConfig: TimelineViewConfig = {
  ...defaultTimelineViewConfig,
  // Banner-specific overrides
  defaultZoom: 1.2, // Slightly zoomed for better banner visibility
  padding: 10, // Reduced padding for banner context
  zoomLevels: {
    ...defaultTimelineViewConfig.zoomLevels,
    full: 1.0, // Full view for banner display
  },
}

/**
 * Timeline banner layout configuration
 * Controls how timeline appears within banner space
 */
export const timelineBannerLayout = {
  showTitle: true, // Display timeline title
  showControls: true, // Show zoom and navigation controls
  showEraLabels: true, // Display era labels and boundaries
  showEventCount: false, // Hide event count for cleaner banner
  controlsPosition: 'bottom' as const, // Position of control buttons
  titlePosition: 'top' as const, // Position of timeline title
  compactMode: false, // Use compact display for smaller banners

  // Banner-specific styling
  backgroundOpacity: 0.8, // Background image opacity
  overlayGradient: 'linear-gradient(rgba(0,0,0,0.3), rgba(0,0,0,0.1))', // Overlay for text readability
  borderRadius: '0.5rem', // Banner border radius

  // Responsive settings
  mobile: {
    showControls: false, // Hide controls on mobile for cleaner look
    showEraLabels: false, // Hide era labels on mobile
    compactMode: true, // Force compact mode on mobile
  },
}

/**
 * Timeline banner interaction configuration
 * Controls user interaction within banner timeline
 */
export const timelineBannerInteraction = {
  enableZoom: true, // Allow zoom in/out
  enablePan: true, // Allow dragging to pan timeline
  enableEventClick: true, // Allow clicking on events
  enableEraNavigation: true, // Allow clicking on eras to navigate
  enableKeyboardControls: false, // Disable keyboard controls in banner

  // Touch/gesture settings
  enableTouch: true, // Enable touch controls on mobile
  pinchToZoom: true, // Enable pinch-to-zoom gesture
  swipeToNavigate: true, // Enable swipe navigation

  // Animation settings
  animationDuration: 300, // Transition duration in milliseconds
  easing: 'ease-in-out', // CSS easing function
}

// =====================================================================
// ERA CONFIGURATION FOR TIMELINE BANNERS
// =====================================================================

/**
 * Enhanced era configuration for banner display
 * Extends default era config with banner-specific styling
 */
export const timelineBannerEraConfig: EraConfigMap = {
  ...defaultEraConfig,

  // Add banner-specific era overrides
  'all-time': {
    ...defaultEraConfig['all-time'],
    backgroundImage: '/posts/timeline/universe.png',
    zoomLevel: 1.0,
    panToYear: 25000,
  },

  'ancient-epoch': {
    ...defaultEraConfig['ancient-epoch'],
    backgroundImage: '/posts/timeline/ancient-epoch.png',
    zoomLevel: 2.5,
  },

  'awakening-era': {
    ...defaultEraConfig['awakening-era'],
    backgroundImage: '/posts/timeline/awakening-era.png',
    zoomLevel: 2.5,
  },

  'golden-age': {
    ...defaultEraConfig['golden-age'],
    backgroundImage: '/posts/timeline/golden-era.png',
    zoomLevel: 2.5,
  },

  'conflict-epoch': {
    ...defaultEraConfig['conflict-epoch'],
    backgroundImage: '/posts/timeline/conflict-era.png',
    zoomLevel: 2.5,
  },

  'transcendent-age': {
    ...defaultEraConfig['transcendent-age'],
    backgroundImage: '/posts/timeline/transcendent-age.png',
    zoomLevel: 2.5,
  },

  'singularity-conflict': {
    ...defaultEraConfig['singularity-conflict'],
    backgroundImage: '/posts/timeline/singularity-conflict.png',
    zoomLevel: 2.0,
  },

  'final-epoch': {
    ...defaultEraConfig['final-epoch'],
    backgroundImage: '/posts/timeline/final-epoch.png',
    zoomLevel: 2.5,
  },
}

/**
 * Timeline banner category configuration
 * Defines available categories and their display properties
 */
export const timelineBannerCategories = {
  'MEGA MEAL': {
    displayName: 'Mega Meal Timeline',
    description: 'The complete chronicle of events',
    color: 'var(--color-primary)',
    icon: 'timeline',
    defaultBackground: '/posts/timeline/universe.png',
  },
  TECH: {
    displayName: 'Technology Timeline',
    description: 'Technological advancement milestones',
    color: 'var(--color-secondary)',
    icon: 'microchip',
    defaultBackground: '/posts/timeline/tech.png',
  },
  HISTORY: {
    displayName: 'Historical Timeline',
    description: 'Major historical events and periods',
    color: 'var(--color-accent)',
    icon: 'scroll',
    defaultBackground: '/posts/timeline/history.png',
  },
  ALL: {
    displayName: 'Complete Timeline',
    description: 'All events across all categories',
    color: 'var(--color-neutral)',
    icon: 'globe',
    defaultBackground: '/posts/timeline/universe.png',
  },
}

// =====================================================================
// HELPER FUNCTIONS
// =====================================================================

/**
 * Get timeline configuration for banner display
 * Combines timeline data with banner-specific settings
 *
 * @param bannerData - Timeline banner configuration
 * @param events - Timeline events to display
 * @returns Complete timeline configuration for banner
 */
export function getTimelineBannerConfig(
  bannerData: TimelineBannerData,
  events: TimelineEvent[] = [],
): {
  viewConfig: TimelineViewConfig
  eraConfig: EraConfigMap
  layoutConfig: typeof timelineBannerLayout
  interactionConfig: typeof timelineBannerInteraction
  statistics: ReturnType<typeof getTimelineStatistics>
  filteredEvents: TimelineEvent[]
} {
  // Filter events by category if specified
  const filteredEvents =
    bannerData.category && bannerData.category !== 'ALL'
      ? events.filter(event => event.category === bannerData.category)
      : events

  // Extract era configuration from events
  const extractedEraConfig = extractEraConfig(filteredEvents)
  const combinedEraConfig = {
    ...timelineBannerEraConfig,
    ...extractedEraConfig,
  }

  // Get timeline statistics
  const statistics = getTimelineStatistics(filteredEvents)

  // Adjust view config based on date range
  const viewConfig = { ...timelineBannerViewConfig }
  if (bannerData.startYear && bannerData.endYear) {
    const range = bannerData.endYear - bannerData.startYear
    const totalRange = statistics.yearSpan || 50000
    const zoomRatio = totalRange / range

    // Adjust zoom based on focus range
    if (zoomRatio > 10) {
      viewConfig.defaultZoom = 3
    } else if (zoomRatio > 5) {
      viewConfig.defaultZoom = 2.5
    } else if (zoomRatio > 2) {
      viewConfig.defaultZoom = 2
    }
  }

  return {
    viewConfig,
    eraConfig: combinedEraConfig,
    layoutConfig: timelineBannerLayout,
    interactionConfig: timelineBannerInteraction,
    statistics,
    filteredEvents,
  }
}

/**
 * Validate timeline banner configuration
 * Ensures timeline settings are properly configured
 *
 * @param config - Timeline banner configuration to validate
 * @returns Validation result with any warnings or errors
 */
export function validateTimelineBannerConfig(config: TimelineBannerData): {
  isValid: boolean
  warnings: string[]
  errors: string[]
} {
  const warnings: string[] = []
  const errors: string[] = []

  // Check if category is provided
  if (!config.category || config.category.trim() === '') {
    errors.push('Category is required for timeline banner')
  }

  // Validate date range if provided
  if (config.startYear && config.endYear) {
    if (config.startYear >= config.endYear) {
      errors.push('Start year must be less than end year')
    }

    if (config.startYear < 0) {
      warnings.push('Start year is negative, which may cause display issues')
    }

    const range = config.endYear - config.startYear
    if (range < 10) {
      warnings.push(
        'Date range is very small (< 10 years), timeline may appear crowded',
      )
    } else if (range > 100000) {
      warnings.push(
        'Date range is very large (> 100,000 years), consider using era-specific view',
      )
    }
  }

  // Check background image if provided
  if (config.background) {
    try {
      if (
        !config.background.startsWith('/') &&
        !config.background.startsWith('http')
      ) {
        warnings.push(
          'Background image path should be absolute or relative URL',
        )
      }
    } catch {
      warnings.push('Invalid background image URL format')
    }
  }

  // Check custom height if provided
  if (config.height) {
    if (!config.height.match(/^\d+(\.\d+)?(px|vh|vw|rem|em|%)$/)) {
      warnings.push(
        'Custom height should be a valid CSS unit (e.g., "70vh", "400px")',
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
 * Get era configuration for specific year range
 * Returns era settings for timeline banner focus area
 *
 * @param startYear - Start year of focus range
 * @param endYear - End year of focus range
 * @returns Era configuration object or null if not found
 */
export function getEraForTimelineRange(
  startYear: number,
  endYear: number,
): { key: string; config: EraConfig } | null {
  const midYear = Math.floor((startYear + endYear) / 2)

  // Find era that contains the middle of the range
  for (const [eraKey, eraConfig] of Object.entries(timelineBannerEraConfig)) {
    if (midYear >= eraConfig.startYear && midYear <= eraConfig.endYear) {
      return { key: eraKey, config: eraConfig }
    }
  }

  return null
}

/**
 * Generate timeline banner background styles
 * Creates CSS styles for timeline banner background
 *
 * @param bannerData - Timeline banner configuration
 * @param selectedEra - Currently selected era (optional)
 * @returns CSS style object
 */
export function getTimelineBannerStyles(
  bannerData: TimelineBannerData,
  selectedEra?: string,
): Record<string, string> {
  let backgroundImage = bannerData.background

  // Use era-specific background if era is selected
  if (selectedEra && timelineBannerEraConfig[selectedEra]?.backgroundImage) {
    backgroundImage = timelineBannerEraConfig[selectedEra].backgroundImage
  }

  // Use category default background if no background specified
  if (
    !backgroundImage &&
    bannerData.category &&
    timelineBannerCategories[bannerData.category]
  ) {
    backgroundImage =
      timelineBannerCategories[bannerData.category].defaultBackground
  }

  const styles: Record<string, string> = {
    position: 'relative',
    overflow: 'hidden',
    borderRadius: timelineBannerLayout.borderRadius,
  }

  if (backgroundImage) {
    styles.backgroundImage = `${timelineBannerLayout.overlayGradient}, url(${backgroundImage})`
    styles.backgroundSize = 'cover'
    styles.backgroundPosition = 'center'
    styles.backgroundRepeat = 'no-repeat'
  }

  if (bannerData.height) {
    styles.height = bannerData.height
  }

  return styles
}

/**
 * Get timeline banner category information
 * Returns category configuration and display properties
 *
 * @param category - Category identifier
 * @returns Category configuration object
 */
export function getTimelineBannerCategory(category: string) {
  return timelineBannerCategories[category] || timelineBannerCategories['ALL']
}

// =====================================================================
// TYPE GUARDS
// =====================================================================

/**
 * Check if data is valid TimelineBannerData
 * Ensures the data has a category string before using it for timeline banners
 *
 * @param data - Data to check
 * @returns True if data is valid TimelineBannerData
 */
export function isTimelineBannerData(data: any): data is TimelineBannerData {
  return (
    data &&
    'category' in data &&
    typeof data.category === 'string' &&
    data.category.trim() !== ''
  )
}

// =====================================================================
// EXPORT CONFIGURATION OBJECT
// =====================================================================

/**
 * Complete timeline banner configuration
 * Combines all settings, data, and helper functions
 */
export const timelineBannerConfig = {
  data: timelineBannerData,
  viewConfig: timelineBannerViewConfig,
  layout: timelineBannerLayout,
  interaction: timelineBannerInteraction,
  eraConfig: timelineBannerEraConfig,
  categories: timelineBannerCategories,

  // Helper functions
  getTimelineBannerConfig,
  validateTimelineBannerConfig,
  getEraForTimelineRange,
  getTimelineBannerStyles,
  getTimelineBannerCategory,
  isTimelineBannerData,

  // Re-export timeline utilities for convenience
  getEraFromYear,
  getEraDisplayName,
  getEraClasses,
  extractEraConfig,
  getTimelineStatistics,
}
