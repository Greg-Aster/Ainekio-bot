// TimelineService.client.ts - Client-safe version without astro:content dependencies
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

// Function to safely handle date serialization issues (client-specific)
export function safeJSONParse(jsonString: string): any {
  try {
    return JSON.parse(jsonString, (key, value) => {
      // Handle date strings in ISO format
      if (
        typeof value === 'string' &&
        /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}.*Z$/.test(value)
      ) {
        return new Date(value)
      }
      return value
    })
  } catch (e) {
    console.error('Error parsing JSON:', e)
    return null
  }
}

// CLIENT-SIDE VERSION of getTimelineEvents - accepts pre-fetched data instead of fetching
export function processTimelineEvents(
  events: TimelineEvent[],
  options: {
    category?: string
    startYear?: number
    endYear?: number
    era?: string
    onlyKeyEvents?: boolean
  } = {},
): TimelineEvent[] {
  const { category, startYear, endYear, era, onlyKeyEvents } = options

  // Make a deep copy to avoid modifying the original events
  let processedEvents = JSON.parse(JSON.stringify(events))

  // Extract era configuration from events
  const eraConfig = extractEraConfig(events)

  // Fill in missing era information based on years and era configuration
  processedEvents = processedEvents.map((event: TimelineEvent) => {
    // Only update era if it's not explicitly set
    if (!event.era) {
      // Convert era configuration to the format expected by getEraFromYear
      const yearRanges: { [key: string]: [number, number] } = {}
      Object.entries(eraConfig).forEach(([eraKey, config]) => {
        yearRanges[eraKey] = [config.startYear, config.endYear]
      })

      const newEvent = { ...event }
      newEvent.era = getEraFromYear(event.year, yearRanges)
      return newEvent
    }
    return event
  })

  // Apply filters
  // In processTimelineEvents function, modify the filter to handle special cases
  processedEvents = processedEvents.filter((event: TimelineEvent) => {
    if (category && event.category !== category) return false
    if (startYear && event.year < startYear) return false
    if (endYear && event.year > endYear) return false
    // Special case for all-eras and all-time - don't filter by era
    if (era && era !== 'all-eras' && era !== 'all-time' && event.era !== era)
      return false
    if (onlyKeyEvents && !event.isKeyEvent) return false
    return true
  })

  // Sort by year ascending
  return processedEvents.sort(
    (a: TimelineEvent, b: TimelineEvent) => a.year - b.year,
  )
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
