import {
  defaultEraConfig,
  defaultEraDisplayNames,
  defaultTimelineViewConfig,
  extractEraConfig,
  getEraClasses,
  getEraConfigForYear,
  getEraDisplayName,
  getEraFromYear,
  getTimelineStatistics,
  groupEventsByEra,
} from '../config/timelineconfig.ts'
// Use 'import type' for types and interfaces
import type {
  EraConfig,
  EraConfigMap,
  TimelineEvent,
  TimelineViewConfig,
} from '../config/timelineconfig.ts'
// TimelineService.ts - Server-side timeline service
import { getSortedPosts } from '../utils/content-utils'

// Modified getTimelineEvents function to include banner posts
export async function getTimelineEvents(
  options: {
    category?: string
    startYear?: number
    endYear?: number
    era?: string
    onlyKeyEvents?: boolean
    includeDrafts?: boolean
    includeBanners?: boolean
  } = {},
): Promise<TimelineEvent[]> {
  const {
    category,
    startYear,
    endYear,
    era,
    onlyKeyEvents,
    includeDrafts = true,
    includeBanners = true,
  } = options

  // Get all posts, including drafts by default for the timeline
  const posts = await getSortedPosts(includeDrafts)

  // First pass: collect all posts with timeline data and extract bannerData
  let timelineEvents = posts
    .filter(post => {
      // Include posts that have either timelineYear or bannerType: "timeline"
      return (
        post.data.timelineYear ||
        (includeBanners && post.data.bannerType === 'timeline')
      )
    })
    .map(post => {
      // If post has timelineYear, use that directly
      if (post.data.timelineYear) {
        const year = Number.parseInt(post.data.timelineYear)
        return {
          title: post.data.title,
          description: post.data.description || '',
          slug: post.slug,
          year,
          era: post.data.timelineEra || '', // We'll determine era later
          category: post.data.category,
          isKeyEvent: post.data.isKeyEvent || false,
          location: post.data.timelineLocation,
          isDraft: post.data.draft || false,
          yIndex: post.data.yIndex,
        }
      }
      // If post has bannerType: "timeline", extract data from bannerData
      else if (post.data.bannerType === 'timeline' && post.data.bannerData) {
        // For banner posts, we'll use the post's publication year if no timelineYear is specified
        const year = post.data.timelineYear
          ? Number.parseInt(post.data.timelineYear)
          : post.data.published?.getFullYear() || new Date().getFullYear()

        return {
          title: post.data.title,
          description: post.data.description || '',
          slug: post.slug,
          year,
          era: post.data.timelineEra || '', // We'll determine era later
          category: post.data.category,
          isKeyEvent: post.data.isKeyEvent || false,
          location: post.data.timelineLocation,
          isDraft: post.data.draft || false,
          yIndex: post.data.yIndex, // Add this line to include the yIndex
          // Include banner-specific data
          bannerData: post.data.bannerData,
        }
      }

      // This should never happen due to our filter, but TypeScript might need it
      return null
    })
    .filter(event => event !== null) as TimelineEvent[]

  // Extract era configuration from banner posts
  const eraConfig = extractEraConfig(timelineEvents)

  // Second pass: fill in missing era information based on years and era configuration
  timelineEvents = timelineEvents.map(event => {
    // Only update era if it's not explicitly set
    if (!event.era) {
      // Convert era configuration to the format expected by getEraFromYear
      const yearRanges: { [key: string]: [number, number] } = {}
      Object.entries(eraConfig).forEach(([eraKey, config]) => {
        yearRanges[eraKey] = [config.startYear, config.endYear]
      })

      event.era = getEraFromYear(event.year, yearRanges)
    }
    return event
  })

  // Apply filters
  timelineEvents = timelineEvents.filter(event => {
    if (category && event.category !== category) return false
    if (startYear && event.year < startYear) return false
    if (endYear && event.year > endYear) return false
    if (era && event.era !== era) return false
    if (onlyKeyEvents && !event.isKeyEvent) return false
    return true
  })

  // Sort by year ascending
  return timelineEvents.sort((a, b) => a.year - b.year)
}

// Re-export these for convenience
export {
  defaultEraConfig,
  defaultEraDisplayNames,
  defaultTimelineViewConfig,
  getEraFromYear,
  getEraDisplayName,
  getEraClasses,
  extractEraConfig,
  groupEventsByEra,
  getTimelineStatistics,
  getEraConfigForYear,
}

// Re-export types
export type { TimelineEvent, EraConfig, EraConfigMap, TimelineViewConfig }
