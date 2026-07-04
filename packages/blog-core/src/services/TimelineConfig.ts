// TimelineConfig.ts - Central configuration for all timeline services

// Define timeline event type
export interface TimelineEvent {
  title: string
  description: string
  slug: string
  year: number
  era?: string
  category?: string
  isKeyEvent: boolean
  location?: string
  isDraft?: boolean
  bannerData?: {
    category?: string
    startYear?: number
    endYear?: number
    background?: string
    eraConfig?: {
      [eraKey: string]: {
        displayName: string
        startYear: number
        endYear: number
      }
    }
  }
}

// Timeline visualization behavior configuration
export interface TimelineViewConfig {
  defaultZoom: number
  maxZoom: number
  minZoom: number
  zoomStep: number
  padding: number
  zoomRatioThresholds: {
    verySmall: number
    small: number
    medium: number
    large: number
    veryLarge: number
  }
  zoomLevels: {
    verySmall: number
    small: number
    medium: number
    large: number
    veryLarge: number
    full: number
  }
}

// Default timeline view configuration
export const defaultTimelineViewConfig: TimelineViewConfig = {
  defaultZoom: 1,
  maxZoom: 5,
  minZoom: 0.5,
  zoomStep: 0.2,
  padding: 15,
  zoomRatioThresholds: {
    verySmall: 50,
    small: 20,
    medium: 10,
    large: 4,
    veryLarge: 2,
  },
  zoomLevels: {
    verySmall: 4,
    small: 3,
    medium: 2.5,
    large: 2,
    veryLarge: 1.5,
    full: 1.2,
  },
}

// Define era display names with ability to customize
export const defaultEraDisplayNames: { [key: string]: string } = {
  'ancient-epoch': 'The Ancient Epoch',
  'awakening-era': 'The Awakening Era',
  'golden-age': 'The Corporate Golden Age',
  'conflict-epoch': 'The Conflict Epoch',
  'singularity-conflict': 'Transtemporal Singularity Conflict',
  'transcendent-age': 'The Transcendent Age',
  'final-epoch': 'The Final Epoch',
  unknown: 'Unknown Era',
}

// Enhanced era configuration type
export interface EraConfig {
  displayName: string
  startYear: number
  endYear: number
  colorClass?: string
  badgeClass?: string
  zoomLevel?: number
  panToYear?: number
  customPadding?: number
  backgroundImage?: string
}

// Era configuration type mapping
export interface EraConfigMap {
  [eraKey: string]: EraConfig
}

// Default era configuration with years
export const defaultEraConfig: EraConfigMap = {
  'all-time': {
    displayName: 'All-Time',
    startYear: 1,
    endYear: 50000,
    zoomLevel: 1,
    panToYear: 25000,
    backgroundImage: '/posts/timeline/universe.png',
  },
  'all-eras': {
    displayName: 'All-Eras',
    startYear: 1,
    endYear: 50000,
    zoomLevel: 1.3,
    panToYear: 25000,
    backgroundImage: '/posts/timeline/universe.png',
  },
  'ancient-epoch': {
    displayName: 'The Ancient Epoch',
    startYear: 1,
    endYear: 5000,
    zoomLevel: 3.5,
    panToYear: 2500,
    backgroundImage: '/posts/timeline/singularity-conflict.png',
  },
  'awakening-era': {
    displayName: 'The Awakening Era',
    startYear: 5001,
    endYear: 15000,
    zoomLevel: 2.75,
    panToYear: 1000,
    backgroundImage: '/posts/timeline/awakening-era.png',
  },
  'golden-age': {
    displayName: 'The Corporate Golden Age',
    startYear: 15001,
    endYear: 25000,
    zoomLevel: 2.75,
    panToYear: 20000,
    backgroundImage: '/posts/timeline/golden-era.png',
  },
  'conflict-epoch': {
    displayName: 'Extinction Epoch',
    startYear: 25001,
    endYear: 35000,
    zoomLevel: 2.75,
    panToYear: 30000,
    backgroundImage: '/posts/timeline/conflict-era.png',
  },
  'transcendent-age': {
    displayName: 'The Transcendent Age',
    startYear: 35001,
    endYear: 45000,
    zoomLevel: 2.75,
    panToYear: 40000,
    backgroundImage: '/posts/timeline/singularity-conflict.png',
  },
  'singularity-conflict': {
    displayName: 'Transtemporal Singularity Conflict',
    startYear: 15000,
    endYear: 48000,
    zoomLevel: 2,
    panToYear: 30000,
    backgroundImage: '/posts/timeline/singularity-conflict.png',
  },
  'final-epoch': {
    displayName: 'The Final Epoch',
    startYear: 45001,
    endYear: 50000,
    zoomLevel: 2.5,
    panToYear: 50000,
    backgroundImage: '/posts/timeline/singularity-conflict.png',
  },
  unknown: {
    displayName: 'Unknown Era',
    startYear: -Infinity,
    endYear: Infinity,
    zoomLevel: 1,
    backgroundImage: '/posts/timeline/singularity-conflict.png',
  },
}

// Helper function to get era ranges
export function getDefaultEraRanges(): { [key: string]: [number, number] } {
  const ranges: { [key: string]: [number, number] } = {}
  Object.entries(defaultEraConfig).forEach(([era, config]) => {
    ranges[era] = [config.startYear, config.endYear]
  })
  return ranges
}

// Function to determine era based on year
export function getEraFromYear(
  year: number,
  eraConfig?: { [key: string]: [number, number] }
): string {
  const defaultRanges = getDefaultEraRanges()
  const config = eraConfig || defaultRanges

  for (const [era, [startYear, endYear]] of Object.entries(config)) {
    if (year >= startYear && year < endYear) {
      if (era === 'singularity-conflict') {
        if (
          year >= defaultRanges['conflict-epoch'][0] &&
          year < defaultRanges['conflict-epoch'][1]
        ) {
          continue
        }
      }
      return era
    }
  }
  return 'unknown'
}

// Find the era configuration for a specific year
export function getEraConfigForYear(
  year: number,
  eraConfigs: EraConfigMap
): { key: string; config: EraConfig } | null {
  const mainEpochs = [
    'ancient-epoch',
    'awakening-era',
    'golden-age',
    'conflict-epoch',
    'transcendent-age',
    'final-epoch',
  ]

  for (const eraKey of mainEpochs) {
    const config = eraConfigs[eraKey]
    if (config && year >= config.startYear && year <= config.endYear) {
      return { key: eraKey, config }
    }
  }

  for (const [eraKey, config] of Object.entries(eraConfigs)) {
    if (
      !mainEpochs.includes(eraKey) &&
      eraKey !== 'all-time' &&
      eraKey !== 'unknown' &&
      year >= config.startYear &&
      year <= config.endYear
    ) {
      return { key: eraKey, config }
    }
  }

  if (
    eraConfigs['all-time'] &&
    year >= eraConfigs['all-time'].startYear &&
    year <= eraConfigs['all-time'].endYear
  ) {
    return { key: 'all-time', config: eraConfigs['all-time'] }
  }

  return null
}

// Function to get display name for era
export function getEraDisplayName(
  era: string,
  customDisplayNames?: { [key: string]: string }
): string {
  if (customDisplayNames && customDisplayNames[era]) {
    return customDisplayNames[era]
  }
  return defaultEraDisplayNames[era] || defaultEraDisplayNames['unknown']
}

// Function to get CSS classes for era
export function getEraClasses(era: string, customConfig?: EraConfigMap): string {
  if (customConfig && customConfig[era] && customConfig[era].badgeClass) {
    return customConfig[era].badgeClass!
  }

  switch (era) {
    case 'ancient-epoch':
      return 'bg-[oklch(0.8_0.1_var(--hue))/0.1] dark:bg-[oklch(0.8_0.1_var(--hue))/0.2] text-[oklch(0.3_0.1_var(--hue))] dark:text-[oklch(0.8_0.1_var(--hue))]'
    case 'awakening-era':
      return 'bg-[oklch(0.7_0.2_var(--hue))/0.1] dark:bg-[oklch(0.7_0.2_var(--hue))/0.2] text-[oklch(0.3_0.2_var(--hue))] dark:text-[oklch(0.7_0.2_var(--hue))]'
    case 'golden-age':
      return 'bg-[oklch(0.6_0.3_var(--hue))/0.1] dark:bg-[oklch(0.6_0.3_var(--hue))/0.2] text-[oklch(0.3_0.3_var(--hue))] dark:text-[oklch(0.6_0.3_var(--hue))]'
    case 'conflict-epoch':
      return 'bg-[oklch(0.5_0.1_var(--hue))/0.1] dark:bg-[oklch(0.5_0.1_var(--hue))/0.2] text-[oklch(0.2_0.1_var(--hue))] dark:text-[oklch(0.5_0.1_var(--hue))]'
    case 'singularity-conflict':
      return 'bg-[oklch(0.4_0.3_var(--hue))/0.1] dark:bg-[oklch(0.4_0.3_var(--hue))/0.2] text-[oklch(0.2_0.3_var(--hue))] dark:text-[oklch(0.4_0.3_var(--hue))]'
    case 'transcendent-age':
      return 'bg-[oklch(0.4_0.2_var(--hue))/0.1] dark:bg-[oklch(0.4_0.2_var(--hue))/0.2] text-[oklch(0.2_0.2_var(--hue))] dark:text-[oklch(0.4_0.2_var(--hue))]'
    case 'final-epoch':
      return 'bg-[oklch(0.3_0.3_var(--hue))/0.1] dark:bg-[oklch(0.3_0.3_var(--hue))/0.2] text-[oklch(0.1_0.3_var(--hue))] dark:text-[oklch(0.3_0.3_var(--hue))]'
    default:
      return 'bg-[oklch(0.9_0.05_var(--hue))/0.1] dark:bg-[oklch(0.3_0.05_var(--hue))/0.2] text-[oklch(0.4_0.05_var(--hue))] dark:text-[oklch(0.9_0.05_var(--hue))]'
  }
}

// Extract era configuration from timeline events
export function extractEraConfig(events: TimelineEvent[]): EraConfigMap {
  const config = { ...defaultEraConfig }
  const bannerEvents = events.filter((event) => event.bannerData?.eraConfig)

  if (bannerEvents.length > 0) {
    const primaryBanner = bannerEvents[0]
    if (primaryBanner.bannerData?.eraConfig) {
      for (const [eraKey, eraSettings] of Object.entries(
        primaryBanner.bannerData.eraConfig
      )) {
        if (config[eraKey]) {
          config[eraKey] = { ...config[eraKey], ...eraSettings }
        } else {
          config[eraKey] = {
            displayName: eraSettings.displayName,
            startYear: eraSettings.startYear,
            endYear: eraSettings.endYear,
            colorClass: '',
            badgeClass: '',
          }
        }
      }
    }
  }
  return config
}

// Function to group events by era
export function groupEventsByEra(events: TimelineEvent[]): {
  [era: string]: TimelineEvent[]
} {
  const grouped: { [era: string]: TimelineEvent[] } = {}

  events.forEach((event) => {
    const era = event.era || 'unknown'
    if (!grouped[era]) {
      grouped[era] = []
    }
    grouped[era].push(event)
  })

  const sortedGrouped: { [era: string]: TimelineEvent[] } = {}
  Object.keys(grouped)
    .sort((a, b) => {
      const aFirstYear = Math.min(...grouped[a].map((e) => e.year))
      const bFirstYear = Math.min(...grouped[b].map((e) => e.year))
      return aFirstYear - bFirstYear
    })
    .forEach((era) => {
      sortedGrouped[era] = grouped[era]
    })

  return sortedGrouped
}

// Function to get timeline statistics
export function getTimelineStatistics(events: TimelineEvent[]): {
  totalEvents: number
  keyEvents: number
  yearSpan: number
  minYear: number
  maxYear: number
  categories: string[]
  eras: string[]
} {
  if (events.length === 0) {
    return {
      totalEvents: 0,
      keyEvents: 0,
      yearSpan: 0,
      minYear: 0,
      maxYear: 0,
      categories: [],
      eras: [],
    }
  }

  const years = events.map((event) => event.year)
  const minYear = Math.min(...years)
  const maxYear = Math.max(...years)

  const uniqueCategories = [
    ...new Set(events.map((event) => event.category).filter(Boolean)),
  ]
  const uniqueEras = [
    ...new Set(events.map((event) => event.era).filter(Boolean)),
  ]

  return {
    totalEvents: events.length,
    keyEvents: events.filter((event) => event.isKeyEvent).length,
    yearSpan: maxYear - minYear,
    minYear,
    maxYear,
    categories: uniqueCategories as string[],
    eras: uniqueEras as string[],
  }
}
