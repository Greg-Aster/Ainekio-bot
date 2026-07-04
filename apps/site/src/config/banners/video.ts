/**
 * ===================================================================
 * VIDEO BANNER CONFIGURATION - YOUTUBE VIDEO EMBEDS
 * ===================================================================
 *
 * This file manages video banner functionality for embedding YouTube videos
 * as dynamic, engaging banner content. It provides configuration for video
 * display, autoplay settings, and responsive video embedding.
 *
 * FEATURES:
 * - YouTube video embedding with configurable parameters
 * - Responsive video sizing and aspect ratio maintenance
 * - Autoplay and loop control options
 * - Video quality and performance optimization
 * - Fallback handling for video loading errors
 *
 * USAGE:
 * - Set videoBannerData.videoId to your YouTube video ID
 * - Use isVideoBannerData() type guard for safe type checking
 * - Configure video parameters for optimal display
 * - Use getVideoEmbedUrl() for generating proper embed URLs
 *
 * MAINTENANCE NOTES:
 * - Update defaultVideoId with your preferred default video
 * - Modify video parameters for different autoplay/quality settings
 * - Adjust aspect ratio settings for different video formats
 * - Configure fallback options for better error handling
 * ===================================================================
 */

import type { VideoBannerData } from './types'

// =====================================================================
// VIDEO BANNER DATA CONFIGURATION
// =====================================================================

/**
 * Default video banner configuration
 * Set the videoId to your preferred YouTube video
 *
 * HOW TO GET VIDEO ID:
 * - From YouTube URL: https://www.youtube.com/watch?v=VIDEO_ID_HERE
 * - Copy the part after 'v=' (e.g., "dQw4w9WgXcQ")
 * - Paste it as the videoId value below
 */
export const videoBannerData: VideoBannerData = {
  videoId: 'YOUR_YOUTUBE_VIDEO_ID_HERE', // Replace with actual YouTube video ID
}

// =====================================================================
// VIDEO DISPLAY CONFIGURATION
// =====================================================================

/**
 * Video embed parameters for YouTube API
 * Controls video behavior, quality, and user interaction
 *
 * PARAMETER EXPLANATIONS:
 * - autoplay: 1 = auto-start video, 0 = wait for user click
 * - mute: 1 = start muted (required for autoplay in most browsers)
 * - loop: 1 = repeat video, 0 = play once
 * - controls: 1 = show player controls, 0 = hide controls
 * - showinfo: 0 = hide video title/uploader info
 * - rel: 0 = don't show related videos at end
 * - fs: 1 = allow fullscreen, 0 = disable fullscreen
 * - modestbranding: 1 = minimal YouTube branding
 */
export const videoParameters = {
  autoplay: 1, // Auto-start video (requires mute in most browsers)
  mute: 1, // Start muted (enables autoplay)
  loop: 1, // Repeat video continuously
  controls: 0, // Hide player controls for cleaner banner look
  showinfo: 0, // Hide video title and uploader info
  rel: 0, // Don't show related videos at end
  fs: 1, // Allow fullscreen capability
  modestbranding: 1, // Minimal YouTube branding
  iv_load_policy: 3, // Hide video annotations
  disablekb: 1, // Disable keyboard controls
  playsinline: 1, // Play inline on iOS (don't open in fullscreen)
}

/**
 * Video quality preferences
 * YouTube will attempt to serve these qualities in order of preference
 *
 * QUALITY OPTIONS:
 * - 'hd1080': 1080p (best quality, higher bandwidth)
 * - 'hd720': 720p (good balance of quality and performance)
 * - 'large': 480p (medium quality, lower bandwidth)
 * - 'medium': 360p (basic quality, minimal bandwidth)
 * - 'small': 240p (lowest quality, very low bandwidth)
 */
export const qualityPreferences = ['hd720', 'hd1080', 'large', 'medium']

/**
 * Video aspect ratio configuration
 * Controls responsive sizing and container dimensions
 */
export const aspectRatioConfig = {
  default: '16:9', // Standard YouTube aspect ratio
  width: '100%', // Full width of container
  minHeight: '300px', // Minimum height for mobile devices
  maxHeight: '80vh', // Maximum height relative to viewport
}

// =====================================================================
// FALLBACK CONFIGURATION
// =====================================================================

/**
 * Fallback options when video fails to load
 * Provides graceful degradation for better user experience
 */
export const videoFallbackConfig = {
  enabled: true, // Enable fallback when video fails
  fallbackType: 'image', // 'image', 'color', or 'gradient'
  fallbackImage: '/assets/banner/video-fallback.jpg', // Fallback image path
  fallbackColor: '#1a1a1a', // Fallback solid color
  fallbackGradient: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)', // Fallback gradient
  showErrorMessage: false, // Show error message to users
  errorMessage: 'Video temporarily unavailable',
}

/**
 * Video loading configuration
 * Controls loading behavior and performance optimization
 */
export const videoLoadingConfig = {
  lazy: true, // Lazy load video for better performance
  preload: 'metadata', // Preload level: 'none', 'metadata', 'auto'
  timeout: 10000, // Video load timeout in milliseconds
  retryAttempts: 3, // Number of retry attempts on failure
  retryDelay: 2000, // Delay between retry attempts
}

// =====================================================================
// HELPER FUNCTIONS
// =====================================================================

/**
 * Generate YouTube embed URL with configured parameters
 * Creates properly formatted URL for embedding videos
 *
 * @param videoId - YouTube video ID
 * @param customParams - Optional custom parameters to override defaults
 * @returns Complete YouTube embed URL
 */
export function getVideoEmbedUrl(
  videoId: string,
  customParams?: Partial<typeof videoParameters>,
): string {
  // Merge default parameters with custom ones
  const params = { ...videoParameters, ...customParams }

  // Add playlist parameter for looping (YouTube requirement)
  if (params.loop === 1) {
    ;(params as any).playlist = videoId
  }

  // Convert parameters to URL search string
  const paramString = Object.entries(params)
    .map(([key, value]) => `${key}=${value}`)
    .join('&')

  return `https://www.youtube.com/embed/${videoId}?${paramString}`
}

/**
 * Extract video ID from various YouTube URL formats
 * Handles different YouTube URL structures and returns clean video ID
 *
 * @param url - YouTube URL in various formats
 * @returns Video ID string or null if not found
 */
export function extractVideoId(url: string): string | null {
  // Handle different YouTube URL formats
  const patterns = [
    /(?:youtube\.com\/watch\?v=|youtu\.be\/|youtube\.com\/embed\/|youtube\.com\/v\/)([a-zA-Z0-9_-]{11})/,
    /youtube\.com\/watch\?.*v=([a-zA-Z0-9_-]{11})/,
  ]

  for (const pattern of patterns) {
    const match = url.match(pattern)
    if (match && match[1]) {
      return match[1]
    }
  }

  // If no pattern matches, assume the input is already a video ID
  if (/^[a-zA-Z0-9_-]{11}$/.test(url)) {
    return url
  }

  return null
}

/**
 * Validate video banner configuration
 * Ensures video ID is properly formatted and configuration is valid
 *
 * @param config - Video banner configuration to validate
 * @returns Validation result with any warnings or errors
 */
export function validateVideoBannerConfig(config: VideoBannerData): {
  isValid: boolean
  warnings: string[]
  errors: string[]
} {
  const warnings: string[] = []
  const errors: string[] = []

  // Check if video ID is provided
  if (!config.videoId || config.videoId.trim() === '') {
    errors.push('Video ID is required for video banner')
  } else if (config.videoId === 'YOUR_YOUTUBE_VIDEO_ID_HERE') {
    errors.push(
      'Default placeholder video ID detected. Please set a real YouTube video ID.',
    )
  } else {
    // Validate video ID format
    const cleanVideoId = extractVideoId(config.videoId)
    if (!cleanVideoId) {
      errors.push('Invalid YouTube video ID format')
    } else if (cleanVideoId !== config.videoId) {
      warnings.push(
        `Video ID appears to be a URL. Consider using just the ID: ${cleanVideoId}`,
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
 * Get video thumbnail URL
 * Returns URL for video thumbnail image (useful for preloading)
 *
 * @param videoId - YouTube video ID
 * @param quality - Thumbnail quality: 'default', 'medium', 'high', 'standard', 'maxres'
 * @returns Thumbnail image URL
 */
export function getVideoThumbnail(
  videoId: string,
  quality: 'default' | 'medium' | 'high' | 'standard' | 'maxres' = 'high',
): string {
  const baseUrl = 'https://img.youtube.com/vi'

  switch (quality) {
    case 'maxres':
      return `${baseUrl}/${videoId}/maxresdefault.jpg`
    case 'standard':
      return `${baseUrl}/${videoId}/sddefault.jpg`
    case 'high':
      return `${baseUrl}/${videoId}/hqdefault.jpg`
    case 'medium':
      return `${baseUrl}/${videoId}/mqdefault.jpg`
    default:
      return `${baseUrl}/${videoId}/default.jpg`
  }
}

/**
 * Generate video iframe attributes
 * Creates properly configured iframe attributes for embedding
 *
 * @param videoId - YouTube video ID
 * @param customParams - Optional custom parameters
 * @returns Object with iframe attributes
 */
export function getVideoIframeAttributes(
  videoId: string,
  customParams?: Partial<typeof videoParameters>,
) {
  const embedUrl = getVideoEmbedUrl(videoId, customParams)

  return {
    src: embedUrl,
    title: 'YouTube video player',
    frameborder: '0',
    allow:
      'accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share',
    allowfullscreen: true,
    loading: videoLoadingConfig.lazy ? 'lazy' : 'eager',
  }
}

// =====================================================================
// TYPE GUARDS
// =====================================================================

/**
 * Check if data is valid VideoBannerData
 * Ensures the data has a videoId string before using it for video banners
 *
 * @param data - Data to check
 * @returns True if data is valid VideoBannerData
 */
export function isVideoBannerData(data: any): data is VideoBannerData {
  return (
    data &&
    'videoId' in data &&
    typeof data.videoId === 'string' &&
    data.videoId.trim() !== ''
  )
}

// =====================================================================
// EXPORT CONFIGURATION OBJECT
// =====================================================================

/**
 * Complete video banner configuration
 * Combines all settings, data, and helper functions
 */
export const videoBannerConfig = {
  data: videoBannerData,
  parameters: videoParameters,
  qualityPreferences,
  aspectRatio: aspectRatioConfig,
  fallback: videoFallbackConfig,
  loading: videoLoadingConfig,

  // Helper functions
  getVideoEmbedUrl,
  extractVideoId,
  validateVideoBannerConfig,
  getVideoThumbnail,
  getVideoIframeAttributes,
  isVideoBannerData,
}
