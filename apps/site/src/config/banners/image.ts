/**
 * ===================================================================
 * IMAGE BANNER CONFIGURATION - STATIC SINGLE IMAGES
 * ===================================================================
 *
 * This file manages static image banner functionality for displaying
 * single images as banner content. It provides configuration for image
 * display, optimization, responsive sizing, and fallback handling.
 *
 * FEATURES:
 * - Static single image display with optimal loading
 * - Responsive image sizing and aspect ratio control
 * - Image optimization and format selection
 * - Lazy loading and performance optimization
 * - Fallback handling for image loading errors
 * - Support for various image formats and sources
 *
 * USAGE:
 * - Set imageBannerData.imageUrl to your image path or URL
 * - Use isImageBannerData() type guard for safe type checking
 * - Configure image display parameters for optimal presentation
 * - Use getOptimizedImageUrl() for performance-optimized images
 *
 * MAINTENANCE NOTES:
 * - Update defaultImageUrl with your preferred default image
 * - Modify optimization settings for different performance requirements
 * - Adjust responsive breakpoints for different screen sizes
 * - Configure fallback options for better error handling
 * ===================================================================
 */

import type { ImageBannerData } from './types'

// =====================================================================
// IMAGE BANNER DATA CONFIGURATION
// =====================================================================

/**
 * Default image banner configuration
 * Set the imageUrl to your preferred default image
 *
 * SUPPORTED FORMATS:
 * - JPEG/JPG: Best for photographs and complex images
 * - PNG: Best for images with transparency or simple graphics
 * - WebP: Modern format with excellent compression (recommended)
 * - AVIF: Next-gen format with superior compression (cutting-edge)
 * - SVG: Vector graphics that scale perfectly
 *
 * URL FORMATS:
 * - Relative paths: '/assets/images/banner.jpg'
 * - Absolute URLs: 'https://example.com/image.jpg'
 * - CDN URLs: 'https://cdn.example.com/optimized/banner.webp'
 */
export const imageBannerData: ImageBannerData = {
  imageUrl: '/path/to/your/default/image.jpg', // Replace with actual image path
}

// =====================================================================
// IMAGE DISPLAY CONFIGURATION
// =====================================================================

/**
 * Image optimization parameters
 * Controls image loading, quality, and performance optimization
 *
 * OPTIMIZATION EXPLANATIONS:
 * - quality: Image quality percentage (1-100, higher = better quality/larger file)
 * - format: Preferred image format for optimization
 * - progressive: Enable progressive JPEG loading
 * - strip: Remove metadata to reduce file size
 * - sharpen: Apply sharpening filter for crisp images
 */
export const imageOptimizationConfig = {
  quality: 85, // Good balance of quality vs file size
  format: 'webp', // Modern format with excellent compression
  progressive: true, // Enable progressive loading for better UX
  strip: true, // Remove EXIF and other metadata
  sharpen: 'mild', // Slight sharpening for crisp display
  blur: 0, // No blur by default
  brightness: 1, // Normal brightness (0.5 = darker, 1.5 = brighter)
  contrast: 1, // Normal contrast (0.5 = lower, 1.5 = higher)
}

/**
 * Responsive image breakpoints
 * Defines different image sizes for different screen sizes
 *
 * BREAKPOINT STRATEGY:
 * - mobile: Optimized for small screens and mobile data
 * - tablet: Medium resolution for tablet devices
 * - desktop: High resolution for desktop displays
 * - retina: Extra high resolution for high-DPI displays
 */
export const responsiveBreakpoints = {
  mobile: {
    maxWidth: 768,
    imageWidth: 800,
    quality: 75,
  },
  tablet: {
    maxWidth: 1024,
    imageWidth: 1200,
    quality: 80,
  },
  desktop: {
    maxWidth: 1920,
    imageWidth: 1600,
    quality: 85,
  },
  retina: {
    maxWidth: Number.POSITIVE_INFINITY,
    imageWidth: 2400,
    quality: 90,
  },
}

/**
 * Image display behavior configuration
 * Controls how images are presented and positioned
 */
export const imageDisplayConfig = {
  objectFit: 'cover' as const, // How image fits container: 'cover', 'contain', 'fill'
  objectPosition: 'center', // Image position: 'center', 'top', 'bottom', etc.
  lazyLoad: true, // Enable lazy loading for better performance
  fadeIn: true, // Smooth fade-in animation when image loads
  fadeInDuration: 300, // Fade-in animation duration in milliseconds
  showLoadingPlaceholder: true, // Show placeholder while image loads
  placeholderColor: '#f3f4f6', // Placeholder background color
  placeholderGradient: 'linear-gradient(135deg, #f3f4f6 0%, #e5e7eb 100%)',
}

// =====================================================================
// FALLBACK CONFIGURATION
// =====================================================================

/**
 * Fallback options when image fails to load
 * Provides graceful degradation for better user experience
 */
export const imageFallbackConfig = {
  enabled: true, // Enable fallback when image fails
  fallbackType: 'gradient' as const, // 'image', 'color', or 'gradient'
  fallbackImage: '/assets/banner/fallback.jpg', // Fallback image path
  fallbackColor: '#1f2937', // Fallback solid color
  fallbackGradient: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)', // Fallback gradient
  showErrorMessage: false, // Show error message to users
  errorMessage: 'Image temporarily unavailable',
  retryAttempts: 3, // Number of retry attempts on failure
  retryDelay: 1000, // Delay between retry attempts in milliseconds
}

/**
 * Image loading performance configuration
 * Controls loading behavior and optimization
 */
export const imageLoadingConfig = {
  preload: false, // Preload image for immediate display
  prefetch: true, // Prefetch for faster subsequent loads
  timeout: 15000, // Image load timeout in milliseconds
  intersection: {
    root: null, // Intersection observer root (null = viewport)
    rootMargin: '50px', // Load images 50px before they enter viewport
    threshold: 0.1, // Trigger when 10% of image area is visible
  },
}

// =====================================================================
// HELPER FUNCTIONS
// =====================================================================

/**
 * Generate optimized image URL with parameters
 * Creates URL with optimization parameters for better performance
 *
 * @param imageUrl - Original image URL
 * @param options - Optimization options
 * @returns Optimized image URL
 */
export function getOptimizedImageUrl(
  imageUrl: string,
  options?: {
    width?: number
    height?: number
    quality?: number
    format?: string
  },
): string {
  // If it's an external URL, return as-is (can't optimize external images)
  if (imageUrl.startsWith('http://') || imageUrl.startsWith('https://')) {
    return imageUrl
  }

  // For local images, we can add optimization parameters
  // This assumes you have an image optimization service set up
  const params = new URLSearchParams()

  if (options?.width) params.set('w', options.width.toString())
  if (options?.height) params.set('h', options.height.toString())
  if (options?.quality) params.set('q', options.quality.toString())
  if (options?.format) params.set('f', options.format)

  const paramString = params.toString()
  const separator = imageUrl.includes('?') ? '&' : '?'

  return paramString ? `${imageUrl}${separator}${paramString}` : imageUrl
}

/**
 * Generate responsive image sources for different screen sizes
 * Creates srcset and sizes attributes for responsive images
 *
 * @param imageUrl - Base image URL
 * @returns Object with srcset and sizes for responsive display
 */
export function getResponsiveImageSources(imageUrl: string): {
  srcset: string
  sizes: string
} {
  const srcsetEntries: string[] = []
  const sizesEntries: string[] = []

  Object.entries(responsiveBreakpoints).forEach(([name, config]) => {
    const optimizedUrl = getOptimizedImageUrl(imageUrl, {
      width: config.imageWidth,
      quality: config.quality,
      format: imageOptimizationConfig.format,
    })

    srcsetEntries.push(`${optimizedUrl} ${config.imageWidth}w`)

    if (config.maxWidth !== Number.POSITIVE_INFINITY) {
      sizesEntries.push(
        `(max-width: ${config.maxWidth}px) ${config.imageWidth}px`,
      )
    }
  })

  // Add default size for largest screens
  sizesEntries.push(`${responsiveBreakpoints.retina.imageWidth}px`)

  return {
    srcset: srcsetEntries.join(', '),
    sizes: sizesEntries.join(', '),
  }
}

/**
 * Validate image banner configuration
 * Ensures image URL is properly formatted and accessible
 *
 * @param config - Image banner configuration to validate
 * @returns Validation result with any warnings or errors
 */
export function validateImageBannerConfig(config: ImageBannerData): {
  isValid: boolean
  warnings: string[]
  errors: string[]
} {
  const warnings: string[] = []
  const errors: string[] = []

  // Check if image URL is provided
  if (!config.imageUrl || config.imageUrl.trim() === '') {
    errors.push('Image URL is required for image banner')
  } else if (config.imageUrl === '/path/to/your/default/image.jpg') {
    errors.push(
      'Default placeholder image URL detected. Please set a real image URL.',
    )
  } else {
    // Validate URL format
    try {
      if (config.imageUrl.startsWith('/')) {
        // Relative URL - assume it's valid
      } else {
        new URL(config.imageUrl) // This will throw if invalid
      }
    } catch {
      errors.push('Invalid image URL format')
    }

    // Check image file extension
    const extension = config.imageUrl.split('.').pop()?.toLowerCase()
    const supportedExtensions = ['jpg', 'jpeg', 'png', 'webp', 'avif', 'svg']

    if (extension && !supportedExtensions.includes(extension)) {
      warnings.push(
        `Image extension ".${extension}" might not be supported. Recommended: ${supportedExtensions.join(', ')}`,
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
 * Generate image loading attributes
 * Creates properly configured image attributes for optimal loading
 *
 * @param imageUrl - Image URL
 * @param alt - Alt text for accessibility
 * @param customOptions - Optional custom configuration
 * @returns Object with image attributes
 */
export function getImageAttributes(
  imageUrl: string,
  alt = 'Banner image',
  customOptions?: {
    eager?: boolean
    sizes?: string
  },
) {
  const responsive = getResponsiveImageSources(imageUrl)

  const attributes: Record<string, any> = {
    src: imageUrl,
    alt,
    loading:
      customOptions?.eager || !imageDisplayConfig.lazyLoad ? 'eager' : 'lazy',
    decoding: 'async',
    fetchpriority: customOptions?.eager ? 'high' : 'auto',
  }

  // Add responsive attributes if supported
  if (responsive.srcset) {
    attributes.srcset = responsive.srcset
    attributes.sizes = customOptions?.sizes || responsive.sizes
  }

  // Add styling attributes
  attributes.style = {
    objectFit: imageDisplayConfig.objectFit,
    objectPosition: imageDisplayConfig.objectPosition,
  }

  return attributes
}

/**
 * Check if image URL is external
 * Determines if image is hosted externally or locally
 *
 * @param imageUrl - Image URL to check
 * @returns True if image is external
 */
export function isExternalImage(imageUrl: string): boolean {
  return imageUrl.startsWith('http://') || imageUrl.startsWith('https://')
}

/**
 * Get image placeholder while loading
 * Returns CSS for placeholder display during image load
 *
 * @param showGradient - Whether to show gradient or solid color
 * @returns CSS background value
 */
export function getImagePlaceholder(showGradient = true): string {
  return showGradient
    ? imageDisplayConfig.placeholderGradient
    : imageDisplayConfig.placeholderColor
}

// =====================================================================
// TYPE GUARDS
// =====================================================================

/**
 * Check if data is valid ImageBannerData
 * Ensures the data has an imageUrl string before using it for image banners
 *
 * @param data - Data to check
 * @returns True if data is valid ImageBannerData
 */
export function isImageBannerData(data: any): data is ImageBannerData {
  return (
    data &&
    'imageUrl' in data &&
    typeof data.imageUrl === 'string' &&
    data.imageUrl.trim() !== ''
  )
}

// =====================================================================
// EXPORT CONFIGURATION OBJECT
// =====================================================================

/**
 * Complete image banner configuration
 * Combines all settings, data, and helper functions
 */
export const imageBannerConfig = {
  data: imageBannerData,
  optimization: imageOptimizationConfig,
  responsive: responsiveBreakpoints,
  display: imageDisplayConfig,
  fallback: imageFallbackConfig,
  loading: imageLoadingConfig,

  // Helper functions
  getOptimizedImageUrl,
  getResponsiveImageSources,
  validateImageBannerConfig,
  getImageAttributes,
  isExternalImage,
  getImagePlaceholder,
  isImageBannerData,
}
