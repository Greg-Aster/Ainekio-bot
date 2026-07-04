import { derived, writable } from 'svelte/store'
import type { Readable, Writable } from 'svelte/store'
import type { TimelineEvent } from '../services/TimelineService.client'
import { processTimelineEvents } from '../services/TimelineService.client'

// Define interface for the timeline view state
interface TimelineViewState {
  // Current view mode
  viewMode: 'timeline' | 'list' | 'tree' | 'map'

  // Display options
  compact: boolean
  asBanner: boolean

  // Navigation state
  scale: number
  offsetX: number
  offsetY: number

  // Event selection
  selectedEventId: string | null

  // Filter options
  category: string | null
  era: string | null
  startYear: number | null
  endYear: number | null
  showOnlyKeyEvents: boolean

  // Visuals
  background: string

  // Events data
  events: TimelineEvent[]

  // Position memory
  lastEra: string | null // Store the last selected era
  lastEraScale: number | null // Store the zoom level for the era
  lastEraOffsetX: number | null // Store the X offset for the era
  lastEraOffsetY: number | null // Store the Y offset for the era
}

// Initial state
const initialState: TimelineViewState = {
  viewMode: 'timeline',
  compact: false,
  asBanner: false,
  scale: 1,
  offsetX: 0,
  offsetY: 0,
  selectedEventId: null,
  category: null,
  era: null,
  startYear: null,
  endYear: null,
  showOnlyKeyEvents: false,
  background: '/assets/banner/0001.png',
  events: [],
  lastEra: null,
  lastEraScale: null,
  lastEraOffsetX: null,
  lastEraOffsetY: null,
}

// Try to load saved preferences from localStorage if available
function loadSavedPreferences(): Partial<TimelineViewState> {
  const savedPrefs: Partial<TimelineViewState> = {}

  try {
    if (typeof window !== 'undefined') {
      // Check if we're in a browser
      console.log('Loading timeline preferences from localStorage')

      // Load view mode preference
      const savedViewMode = localStorage.getItem('timeline-view-preference')
      if (
        savedViewMode &&
        ['timeline', 'list', 'tree', 'map'].includes(savedViewMode)
      ) {
        savedPrefs.viewMode = savedViewMode as any
        console.log(`Loaded view mode: ${savedViewMode}`)
      }

      // Load compact mode preference
      const savedCompact = localStorage.getItem('timeline-compact-mode')
      if (savedCompact) {
        savedPrefs.compact = savedCompact === 'true'
        console.log(`Loaded compact mode: ${savedCompact}`)
      }

      // Load last selected era
      const savedEra = localStorage.getItem('timeline-last-era')
      if (savedEra) {
        savedPrefs.lastEra = savedEra
        savedPrefs.era = savedEra // Also set as current era
        console.log(`Loaded era: ${savedEra}`)
      } else {
        // Explicit default: no era selected (all time view)
        console.log('No saved era found, defaulting to null (all time)')
        savedPrefs.lastEra = null
        savedPrefs.era = null
      }

      // Load navigation state for the era
      const savedScale = localStorage.getItem('timeline-last-era-scale')
      if (savedScale) {
        const scale = Number.parseFloat(savedScale)
        if (!isNaN(scale) && isFinite(scale) && scale > 0) {
          savedPrefs.lastEraScale = scale
          savedPrefs.scale = scale
          console.log(`Loaded scale: ${scale}`)
        } else {
          console.warn(`Invalid saved scale: ${savedScale}`)
        }
      }

      const savedOffsetX = localStorage.getItem('timeline-last-era-offset-x')
      if (savedOffsetX) {
        const offsetX = Number.parseFloat(savedOffsetX)
        if (!isNaN(offsetX) && isFinite(offsetX)) {
          savedPrefs.lastEraOffsetX = offsetX
          savedPrefs.offsetX = offsetX
          console.log(`Loaded offsetX: ${offsetX}`)
        } else {
          console.warn(`Invalid saved offsetX: ${savedOffsetX}`)
        }
      }

      const savedOffsetY = localStorage.getItem('timeline-last-era-offset-y')
      if (savedOffsetY) {
        const offsetY = Number.parseFloat(savedOffsetY)
        if (!isNaN(offsetY) && isFinite(offsetY)) {
          savedPrefs.lastEraOffsetY = offsetY
          savedPrefs.offsetY = offsetY
          console.log(`Loaded offsetY: ${offsetY}`)
        } else {
          console.warn(`Invalid saved offsetY: ${savedOffsetY}`)
        }
      }
    }
  } catch (e) {
    // Ignore localStorage errors (happens in incognito or when storage is disabled)
    console.log('Unable to load timeline preferences from localStorage:', e)

    // Set defaults on error
    savedPrefs.lastEra = null
    savedPrefs.era = null
  }

  return savedPrefs
}

// Save current view state to localStorage with better validation
function saveViewState(state: TimelineViewState) {
  try {
    if (typeof window !== 'undefined') {
      console.log('Saving timeline preferences to localStorage')

      // Save view mode
      localStorage.setItem('timeline-view-preference', state.viewMode)

      // Save compact mode
      localStorage.setItem('timeline-compact-mode', String(state.compact))

      // Save current era if set
      if (state.era) {
        console.log(`Saving era to localStorage: ${state.era}`)
        localStorage.setItem('timeline-last-era', state.era)
      } else if (state.lastEra) {
        // If we're setting era to null but have a lastEra, make sure we don't lose it
        console.log(`Maintaining lastEra in localStorage: ${state.lastEra}`)
      } else {
        // If no era is selected, clear the saved era
        console.log('Clearing saved era (setting to null)')
        localStorage.removeItem('timeline-last-era')
      }

      // Save navigation state only if we have valid numbers
      if (isFinite(state.scale) && state.scale > 0) {
        localStorage.setItem('timeline-last-era-scale', String(state.scale))
      } else {
        console.warn(`Not saving invalid scale: ${state.scale}`)
      }

      if (isFinite(state.offsetX)) {
        localStorage.setItem(
          'timeline-last-era-offset-x',
          String(state.offsetX),
        )
      } else {
        console.warn(`Not saving invalid offsetX: ${state.offsetX}`)
      }

      if (isFinite(state.offsetY)) {
        localStorage.setItem(
          'timeline-last-era-offset-y',
          String(state.offsetY),
        )
      } else {
        console.warn(`Not saving invalid offsetY: ${state.offsetY}`)
      }
    }
  } catch (e) {
    // Ignore localStorage errors
    console.log('Unable to save timeline preferences to localStorage', e)
  }
}

// Create the main store with merged preferences
const savedPrefs = loadSavedPreferences()
const baseStore = writable<TimelineViewState>({
  ...initialState,
  ...savedPrefs,
})

// Create action functions for updating the store
const actions = {
  // Set initial events
  setInitialEvents: (events: TimelineEvent[]): void =>
    baseStore.update(state => ({ ...state, events })),

  // Reset to initial state
  reset: (): void => baseStore.set(initialState),

  // Set view mode
  setViewMode: (mode: 'timeline' | 'list' | 'tree' | 'map'): void => {
    baseStore.update(state => {
      const newState = { ...state, viewMode: mode }
      saveViewState(newState)
      return newState
    })
  },

  // Toggle compact mode
  toggleCompact: (): void => {
    baseStore.update(state => {
      const newState = { ...state, compact: !state.compact }
      saveViewState(newState)
      return newState
    })
  },

  // Set banner mode
  setBannerMode: (asBanner: boolean): void =>
    baseStore.update(state => ({ ...state, asBanner })),

  // Navigation controls
  zoomIn: (): void =>
    baseStore.update(state => {
      const newScale = Math.min(5, state.scale + 0.2)
      const newState = { ...state, scale: newScale }
      saveViewState(newState)
      return newState
    }),

  zoomOut: (): void =>
    baseStore.update(state => {
      const newScale = Math.max(0.5, state.scale - 0.2)
      const newState = { ...state, scale: newScale }
      saveViewState(newState)
      return newState
    }),

  pan: (deltaX: number, deltaY: number): void =>
    baseStore.update(state => {
      const newState = {
        ...state,
        offsetX: state.offsetX + deltaX,
        offsetY: state.offsetY + deltaY,
      }
      saveViewState(newState)
      return newState
    }),

  resetView: (): void =>
    baseStore.update(state => {
      const newState = {
        ...state,
        scale: 1,
        offsetX: 0,
        offsetY: 0,
      }
      saveViewState(newState)
      return newState
    }),

  // Selection
  selectEvent: (eventId: string | null): void =>
    baseStore.update(state => ({ ...state, selectedEventId: eventId })),

  // Filters
  setCategory: (category: string | null): void =>
    baseStore.update(state => ({ ...state, category })),

  setEra: (era: string | null): void =>
    baseStore.update(state => {
      console.log(`Setting era in store: ${era}`)
      const newState = { ...state, era, lastEra: era }
      saveViewState(newState)
      return newState
    }),

  setYearRange: (startYear: number | null, endYear: number | null): void =>
    baseStore.update(state => ({ ...state, startYear, endYear })),

  toggleKeyEventsOnly: (): void =>
    baseStore.update(state => ({
      ...state,
      showOnlyKeyEvents: !state.showOnlyKeyEvents,
    })),

  setBackground: (background: string): void =>
    baseStore.update(state => ({ ...state, background })),

  // Save the current position for the current era
  saveEraPosition: (scale: number, offsetX: number, offsetY: number): void =>
    baseStore.update(state => {
      // Validate inputs to avoid NaN or infinite values
      if (!isFinite(scale) || !isFinite(offsetX) || !isFinite(offsetY)) {
        console.warn('Invalid position values:', { scale, offsetX, offsetY })
        return state
      }

      // Only update if we have a valid era
      if (!state.era) {
        console.log('Not saving position - no era selected')
        return state
      }

      console.log(`Saving position for era ${state.era}:`, {
        scale,
        offsetX,
        offsetY,
      })

      const newState = {
        ...state,
        scale,
        offsetX,
        offsetY,
        lastEraScale: scale,
        lastEraOffsetX: offsetX,
        lastEraOffsetY: offsetY,
      }
      saveViewState(newState)
      return newState
    }),
}

// Export a combined store with both the writable store methods and our action methods
export const timelineStore: Writable<TimelineViewState> & typeof actions = {
  subscribe: baseStore.subscribe,
  set: baseStore.set,
  update: baseStore.update,
  ...actions,
}

// Export actions separately for use where direct imports are needed
export const timelineActions: typeof actions = actions

// Create a derived store for current filtered events
export const filteredEvents: Readable<TimelineEvent[]> = derived(
  baseStore,
  ($store, set) => {
    // Filter events based on current filters
    const filtered = processTimelineEvents($store.events, {
      category: $store.category || undefined,
      startYear: $store.startYear || undefined,
      endYear: $store.endYear || undefined,
      era:
        $store.era === 'all-eras' || $store.era === 'all-time'
          ? undefined
          : $store.era ?? undefined,
      onlyKeyEvents: $store.showOnlyKeyEvents,
    })

    set(filtered)
  },
  [] as TimelineEvent[],
)

// Create a derived store for the selected event
export const selectedEvent: Readable<TimelineEvent | null> = derived(
  [baseStore, filteredEvents],
  ([$store, $events]) => {
    if (!$store.selectedEventId) return null
    return $events.find(event => event.slug === $store.selectedEventId) || null
  },
)
