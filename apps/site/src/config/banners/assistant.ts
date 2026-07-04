/**
 * ===================================================================
 * ASSISTANT BANNER CONFIGURATION - AI ASSISTANT INTERACTIVE BANNERS
 * ===================================================================
 *
 * This file manages AI assistant (Bleepy) banner functionality for displaying
 * interactive assistant interfaces as engaging banner content. It provides
 * configuration for assistant appearance, interaction patterns, and
 * dynamic content generation.
 *
 * FEATURES:
 * - Interactive AI assistant interface within banner space
 * - Customizable assistant personality and appearance
 * - Dynamic greeting and message generation
 * - Responsive assistant layout for different screen sizes
 * - Integration with site-wide assistant functionality
 * - Animated assistant interactions and responses
 *
 * USAGE:
 * - Configure assistant appearance and personality settings
 * - Set background images and visual styling
 * - Use isAssistantBannerData() type guard for safe type checking
 * - Customize assistant greetings and interaction patterns
 *
 * MAINTENANCE NOTES:
 * - Update assistant personality settings to match your brand
 * - Modify greeting messages for different contexts
 * - Adjust interaction patterns for optimal user engagement
 * - Configure background images and visual styling
 * ===================================================================
 */

import type { AssistantBannerData } from './types'

// =====================================================================
// ASSISTANT BANNER DATA CONFIGURATION
// =====================================================================

/**
 * Default assistant banner configuration
 * Set imageUrl for background image behind assistant interface
 *
 * BACKGROUND OPTIONS:
 * - Use atmospheric/ambient images that don't distract from assistant
 * - Consider gradients or subtle patterns for better text readability
 * - Leave undefined for default gradient background
 * - Use high-resolution images for crisp display across devices
 */
export const assistantBannerData: AssistantBannerData = {
  imageUrl: '/path/to/assistant/background.jpg', // Optional background for assistant banner
}

// =====================================================================
// ASSISTANT PERSONALITY CONFIGURATION
// =====================================================================

/**
 * Assistant personality and appearance settings
 * Defines how the assistant appears and behaves in banner context
 */
export const assistantPersonality = {
  name: 'Bleepy', // Assistant name
  title: 'AI Assistant', // Assistant title/role
  avatar: '/assets/assistant/bleepy.png', // Assistant avatar image

  // Personality traits
  personality: {
    tone: 'friendly' as const, // "professional", "friendly", "casual", "formal"
    humor: 'mild' as const, // "none", "mild", "moderate", "high"
    helpfulness: 'high' as const, // "low", "medium", "high"
    curiosity: 'medium' as const, // "low", "medium", "high"
  },

  // Voice and communication style
  communication: {
    greetingStyle: 'contextual' as const, // "formal", "casual", "contextual", "time-based"
    responseLength: 'concise' as const, // "brief", "concise", "detailed", "comprehensive"
    useEmojis: true, // Include emojis in responses
    usePersonalization: true, // Personalize responses based on context
  },
}

/**
 * Assistant banner greetings and messages
 * Dynamic greetings based on context, time, and user interaction
 */
export const assistantGreetings = {
  // Time-based greetings
  morning: [
    'Good morning! ☀️ Ready to explore?',
    'Rise and shine! 🌅 What can I help you discover today?',
    "Morning! ☕ Let's start your day with something interesting.",
    'Hello there! 🌞 The day is full of possibilities!',
  ],

  afternoon: [
    'Good afternoon! 🌤️ What brings you here today?',
    'Afternoon! ☀️ How can I assist your exploration?',
    'Hello! 🌻 Ready for an adventure?',
    'Hi there! 🌸 What would you like to discover?',
  ],

  evening: [
    'Good evening! 🌙 Perfect time for some discovery.',
    'Evening! ✨ What sparks your curiosity tonight?',
    "Hello! 🌆 Let's explore something fascinating.",
    'Hi there! 🌟 Ready for an evening of exploration?',
  ],

  night: [
    'Good evening! 🌃 Night owls deserve the best discoveries.',
    'Hello night explorer! 🦉 What can I help you find?',
    'Hi there! 🌙 Perfect time for deep exploration.',
    "Evening! ⭐ Let's dive into something interesting.",
  ],

  // Context-based greetings
  firstVisit: [
    "Welcome! 🎉 I'm Bleepy, your AI guide. Ready to explore?",
    'Hello there! 👋 First time here? Let me show you around!',
    "Welcome aboard! 🚀 I'm here to help you discover amazing things.",
    "Hi! ✨ New to the site? I'd love to be your guide!",
  ],

  returning: [
    'Welcome back! 😊 Ready for another adventure?',
    'Hey there! 👋 Great to see you again!',
    'Hello again! 🎈 What would you like to explore today?',
    "Hi! 🌟 Back for more discoveries? I'm excited to help!",
  ],

  // Generic/fallback greetings
  default: [
    "Hello! 👋 I'm Bleepy, your AI assistant. How can I help?",
    'Hi there! ✨ Ready to explore something amazing?',
    "Hello! 🌟 I'm here to help you discover great content.",
    'Hi! 🎯 What would you like to explore today?',
  ],
}

// =====================================================================
// ASSISTANT BANNER LAYOUT CONFIGURATION
// =====================================================================

/**
 * Assistant banner layout and visual settings
 * Controls how assistant interface appears within banner space
 */
export const assistantBannerLayout = {
  // Layout positioning
  position: 'center' as const, // "left", "center", "right", "floating"
  alignment: 'middle' as const, // "top", "middle", "bottom"

  // Size and spacing
  containerPadding: '2rem', // Padding around assistant container
  avatarSize: '4rem', // Size of assistant avatar
  maxWidth: '600px', // Maximum width of assistant container
  minHeight: '200px', // Minimum height for banner

  // Visual styling
  backgroundOpacity: 0.9, // Background overlay opacity
  borderRadius: '1rem', // Container border radius
  shadowIntensity: 'medium' as const, // "none", "light", "medium", "strong"

  // Animation settings
  animateEntrance: true, // Animate assistant appearance
  entranceDelay: 500, // Delay before entrance animation (ms)
  entranceAnimation: 'fadeInUp' as const, // "fadeIn", "fadeInUp", "slideIn", "bounce"

  // Interactive elements
  showTypingIndicator: true, // Show typing animation
  showPulseEffect: true, // Subtle pulse on avatar
  enableHoverEffects: true, // Hover effects on interactive elements
}

/**
 * Assistant banner interaction configuration
 * Controls user interaction patterns and response behavior
 */
export const assistantBannerInteraction = {
  // Interaction modes
  mode: 'banner' as const, // "banner", "chat", "assistant", "guide"
  autoGreet: true, // Automatically show greeting
  greetingDelay: 1000, // Delay before auto-greeting (ms)

  // Response behavior
  quickResponses: true, // Show quick response buttons
  contextAware: true, // Use page context for responses
  rememberInteraction: false, // Remember user preferences (banner mode)

  // Available actions
  actions: {
    showSearch: true, // Show search functionality
    showNavigation: true, // Show site navigation help
    showHelp: true, // Show general help options
    showContact: false, // Show contact options (minimal in banner)
    showCustomActions: true, // Show custom page-specific actions
  },
}

// =====================================================================
// ASSISTANT BANNER QUICK ACTIONS
// =====================================================================

/**
 * Quick action buttons for assistant banner
 * Provides common actions users can take directly from banner
 */
export const assistantQuickActions = [
  {
    id: 'explore',
    label: 'Explore Site',
    icon: 'compass',
    description: 'Show me around the site',
    action: 'navigation',
  },
  {
    id: 'search',
    label: 'Search',
    icon: 'search',
    description: 'Find specific content',
    action: 'search',
  },
  {
    id: 'recent',
    label: "What's New",
    icon: 'sparkles',
    description: 'Show recent updates',
    action: 'recent_content',
  },
  {
    id: 'popular',
    label: 'Popular',
    icon: 'trending-up',
    description: 'Show popular content',
    action: 'popular_content',
  },
]

/**
 * Context-specific actions based on page type
 * Different actions appear based on current page context
 */
export const contextualActions = {
  home: [
    {
      id: 'get_started',
      label: 'Get Started',
      icon: 'play',
      description: 'Show me how to begin',
      action: 'onboarding',
    },
    {
      id: 'featured',
      label: 'Featured Content',
      icon: 'star',
      description: 'Show featured posts',
      action: 'featured_content',
    },
  ],

  blog: [
    {
      id: 'categories',
      label: 'Browse Categories',
      icon: 'folder',
      description: 'Explore content categories',
      action: 'show_categories',
    },
    {
      id: 'timeline',
      label: 'Timeline View',
      icon: 'timeline',
      description: 'View posts chronologically',
      action: 'show_timeline',
    },
  ],

  post: [
    {
      id: 'related',
      label: 'Related Posts',
      icon: 'link',
      description: 'Find similar content',
      action: 'show_related',
    },
    {
      id: 'summary',
      label: 'Summarize',
      icon: 'file-text',
      description: 'Get a quick summary',
      action: 'summarize_post',
    },
  ],

  about: [
    {
      id: 'contact',
      label: 'Get in Touch',
      icon: 'mail',
      description: 'Contact information',
      action: 'show_contact',
    },
    {
      id: 'story',
      label: 'Our Story',
      icon: 'book',
      description: 'Learn more about us',
      action: 'show_story',
    },
  ],
}

// =====================================================================
// ASSISTANT BANNER STYLING
// =====================================================================

/**
 * Visual styling configuration for assistant banner
 * CSS-in-JS styling options for different themes and appearances
 */
export const assistantBannerStyling = {
  // Theme variants
  themes: {
    light: {
      background: 'rgba(255, 255, 255, 0.95)',
      text: '#1f2937',
      accent: '#3b82f6',
      border: 'rgba(0, 0, 0, 0.1)',
    },
    dark: {
      background: 'rgba(17, 24, 39, 0.95)',
      text: '#f9fafb',
      accent: '#60a5fa',
      border: 'rgba(255, 255, 255, 0.1)',
    },
    glass: {
      background: 'rgba(255, 255, 255, 0.1)',
      text: '#1f2937',
      accent: '#8b5cf6',
      border: 'rgba(255, 255, 255, 0.2)',
      backdropFilter: 'blur(10px)',
    },
  },

  // Current theme
  currentTheme: 'glass' as const,

  // Custom CSS properties
  customProperties: {
    '--assistant-font-family': 'system-ui, sans-serif',
    '--assistant-font-size': '0.875rem',
    '--assistant-line-height': '1.5',
    '--assistant-transition': 'all 0.2s ease-in-out',
  },
}

// =====================================================================
// HELPER FUNCTIONS
// =====================================================================

/**
 * Get contextual greeting based on time and user context
 * Returns appropriate greeting message for current context
 *
 * @param context - User context information
 * @returns Greeting message string
 */
export function getContextualGreeting(context?: {
  timeOfDay?: 'morning' | 'afternoon' | 'evening' | 'night'
  isFirstVisit?: boolean
  pageType?: string
}): string {
  const now = new Date()
  const hour = now.getHours()

  // Determine time of day if not provided
  let timeOfDay = context?.timeOfDay
  if (!timeOfDay) {
    if (hour < 12) timeOfDay = 'morning'
    else if (hour < 17) timeOfDay = 'afternoon'
    else if (hour < 21) timeOfDay = 'evening'
    else timeOfDay = 'night'
  }

  // Choose greeting category
  let greetingCategory: keyof typeof assistantGreetings
  if (context?.isFirstVisit) {
    greetingCategory = 'firstVisit'
  } else if (context?.isFirstVisit === false) {
    greetingCategory = 'returning'
  } else {
    greetingCategory = timeOfDay
  }

  // Get random greeting from category
  const greetings =
    assistantGreetings[greetingCategory] || assistantGreetings.default
  return greetings[Math.floor(Math.random() * greetings.length)]
}

/**
 * Get quick actions for current page context
 * Returns relevant quick actions based on page type
 *
 * @param pageType - Current page type
 * @returns Array of quick action objects
 */
export function getContextualQuickActions(pageType?: string) {
  const baseActions = [...assistantQuickActions]
  const contextActions = pageType
    ? contextualActions[pageType as keyof typeof contextualActions] || []
    : []

  return [...baseActions, ...contextActions]
}

/**
 * Validate assistant banner configuration
 * Ensures assistant settings are properly configured
 *
 * @param config - Assistant banner configuration to validate
 * @returns Validation result with any warnings or errors
 */
export function validateAssistantBannerConfig(config: AssistantBannerData): {
  isValid: boolean
  warnings: string[]
  errors: string[]
} {
  const warnings: string[] = []
  const errors: string[] = []

  // Check background image if provided
  if (config.imageUrl) {
    if (config.imageUrl === '/path/to/assistant/background.jpg') {
      warnings.push(
        'Default placeholder background URL detected. Consider setting a real background image.',
      )
    } else {
      try {
        if (
          !config.imageUrl.startsWith('/') &&
          !config.imageUrl.startsWith('http')
        ) {
          warnings.push(
            'Background image path should be absolute or relative URL',
          )
        }
      } catch {
        warnings.push('Invalid background image URL format')
      }
    }
  }

  // Validate personality configuration
  if (assistantPersonality.avatar === '/assets/assistant/bleepy.png') {
    warnings.push(
      'Default assistant avatar path detected. Consider customizing the avatar.',
    )
  }

  // Check if required features are properly configured
  if (
    assistantBannerInteraction.autoGreet &&
    assistantGreetings.default.length === 0
  ) {
    errors.push('Auto-greet is enabled but no default greetings are configured')
  }

  return {
    isValid: errors.length === 0,
    warnings,
    errors,
  }
}

/**
 * Generate assistant banner styles
 * Creates CSS styles for assistant banner appearance
 *
 * @param config - Assistant banner configuration
 * @param theme - Optional theme override
 * @returns CSS style object
 */
export function getAssistantBannerStyles(
  config: AssistantBannerData,
  theme?: keyof typeof assistantBannerStyling.themes,
): Record<string, string> {
  const currentTheme = theme || assistantBannerStyling.currentTheme
  const themeStyles = assistantBannerStyling.themes[currentTheme]

  const styles: Record<string, string> = {
    position: 'relative',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    minHeight: assistantBannerLayout.minHeight,
    padding: assistantBannerLayout.containerPadding,
    borderRadius: assistantBannerLayout.borderRadius,
    background: themeStyles.background,
    color: themeStyles.text,
    border: `1px solid ${themeStyles.border}`,
    ...assistantBannerStyling.customProperties,
  }

  // Add backdrop filter for glass theme
  if (currentTheme === 'glass' && themeStyles.backdropFilter) {
    styles.backdropFilter = themeStyles.backdropFilter
  }

  // Add background image if provided
  if (config.imageUrl) {
    styles.backgroundImage = `linear-gradient(rgba(0,0,0,${1 - assistantBannerLayout.backgroundOpacity}), rgba(0,0,0,${1 - assistantBannerLayout.backgroundOpacity})), url(${config.imageUrl})`
    styles.backgroundSize = 'cover'
    styles.backgroundPosition = 'center'
    styles.backgroundRepeat = 'no-repeat'
  }

  return styles
}

/**
 * Get assistant avatar with fallback
 * Returns avatar URL with fallback options
 *
 * @param customAvatar - Optional custom avatar URL
 * @returns Avatar URL string
 */
export function getAssistantAvatar(customAvatar?: string): string {
  if (customAvatar && customAvatar.trim() !== '') {
    return customAvatar
  }

  return assistantPersonality.avatar
}

// =====================================================================
// TYPE GUARDS
// =====================================================================

/**
 * Check if data is valid AssistantBannerData
 * Validates assistant banner data structure
 *
 * @param data - Data to check
 * @returns True if data is valid AssistantBannerData
 */
export function isAssistantBannerData(data: any): data is AssistantBannerData {
  return (
    data &&
    typeof data === 'object' &&
    !('videoId' in data) &&
    !('imageUrl' in data) &&
    !('category' in data)
  )
}

// =====================================================================
// EXPORT CONFIGURATION OBJECT
// =====================================================================

/**
 * Complete assistant banner configuration
 * Combines all settings, data, and helper functions
 */
export const assistantBannerConfig = {
  data: assistantBannerData,
  personality: assistantPersonality,
  greetings: assistantGreetings,
  layout: assistantBannerLayout,
  interaction: assistantBannerInteraction,
  quickActions: assistantQuickActions,
  contextualActions,
  styling: assistantBannerStyling,

  // Helper functions
  getContextualGreeting,
  getContextualQuickActions,
  validateAssistantBannerConfig,
  getAssistantBannerStyles,
  getAssistantAvatar,
  isAssistantBannerData,
}
