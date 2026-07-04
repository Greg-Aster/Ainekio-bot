# Timeline System Documentation

This document provides an overview of the timeline system for the Qarnivor universe, including component relationships, file organization, and implementation details.

## System Architecture

The timeline system is composed of several interconnected components that work together to create an interactive visualization of chronological events.

```
┌─────────────────────┐      ┌─────────────────────┐
│  TimelineService.ts │◄────►│  MDX Content Files  │
└──────────┬──────────┘      └─────────────────────┘
           │
           ▼
┌─────────────────────┐      ┌─────────────────────┐
│   Core Components   │◄────►│     Page Routes     │
└──────────┬──────────┘      └─────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────────┐
│                  User Interface                  │
└─────────────────────────────────────────────────┘
```

## File Map

### 1. Core Service

- **`src/services/TimelineService.ts`**
  - Central data provider for all timeline components
  - Fetches and processes timeline events from MDX files
  - Provides utility functions for era classification, display names, etc.
  - Handles filtering, sorting, and grouping of timeline data

### 2. Core Components

- **`src/components/FictionTimeline.astro`**
  - Horizontal timeline visualization
  - Renders events as nodes along a central line
  - Positions events in top/bottom layout to avoid overlapping
  - Provides interactive hover and click behaviors

- **`src/components/widget/TimelineWidget.astro`**
  - Compact widget that shows recent or filtered timeline events
  - Used in sidebars and related content sections
  - Customizable with various filtering options (category, date range, key events)

- **`src/components/widget/TimelineController.astro`**
  - Control panel for timeline visualization
  - Provides zoom, era filtering, and compact/expanded view options
  - Wraps FictionTimeline for enhanced interactivity

- **`src/components/TimelineNavigation.astro`**
  - Multi-view timeline browser
  - Offers List View, Tree View, and Map View options
  - Groups events by era and provides detailed information

- **`src/components/widget/WidgetLayout.astro`**
  - Container component used by timeline components
  - Provides consistent styling and collapsible behavior

### 3. Page Routes

- **`src/pages/timeline/index.astro`**
  - Main timeline hub page
  - Shows comprehensive timeline overview
  - Provides statistics and category links
  - Target of "View Full Interactive Timeline" links

- **`src/pages/timeline/[category].astro`**
  - Category-specific timeline page
  - Dynamic route that generates pages for each category
  - Shows filtered timeline with category-specific statistics

- **`src/pages/[...category].astro`**
  - Route configuration for category timelines
  - Connects URL paths to the category timeline component

### 4. Timeline CSS

- **`src/styles/timeline.css`**
  - Shared CSS for timeline components
  - Includes animations, transitions, and responsive styles
  - Ensures consistent visual appearance across components

### 5. MDX Content Files

- **`src/content/posts/Great-Devourment.mdx`**
- **`src/content/posts/Spork-Rebellion.mdx`**
- **`src/content/posts/Snuggaloid-Emergence.mdx`**
- **`src/content/posts/Qarnivor-Timeline-Overview.mdx`**
- **`src/content/posts/Universe-Timeline.mdx`**
- **`src/content/posts/timeline-demo.mdx`**
  - Content files that include timeline metadata
  - Each represents an event in the timeline
  - Uses frontmatter properties (timelineYear, timelineEra, etc.)

## Key Frontmatter Properties

Timeline events are defined in MDX frontmatter with these properties:

```yaml
---
title: "Event Title"            # Title of the event
timelineYear: 3042              # Year when the event occurred (required)
timelineEra: "spork-uprising"   # Era classification (optional)
timelineLocation: "Location"    # Location for map placement (optional)
isKeyEvent: true                # Marks as historically significant (optional)
category: "MEGA MEAL"           # Content category (optional)
---
```

## Component Interaction Flow

1. **Data Fetching**: TimelineService retrieves event data from MDX files
2. **Data Processing**: Service filters, sorts, and groups events as needed
3. **Visualization**: Components render the processed data in various formats
4. **User Interaction**: Controllers handle user input for filtering/navigation
5. **Page Integration**: Timeline components are embedded in MDX content

## Usage Examples

### Basic Timeline Widget

```astro
<TimelineWidget 
  category="MEGA MEAL" 
  count={3} 
/>
```

### Interactive Timeline with Controller

```astro
<TimelineController 
  title="Qarnivor Timeline" 
  category="MEGA MEAL"
  startYear={3040}
  endYear={3050}
  isCollapsed={false}
  compact={false}
/>
```

### Multi-view Timeline Navigator

```astro
<WidgetLayout id="timeline-browser" name="Timeline Browser">
  <TimelineNavigation 
    category="MEGA MEAL" 
    view="list" 
  />
</WidgetLayout>
```

## Design Philosophy

The timeline system follows these design principles:

1. **Modularity**: Components can be used independently or combined
2. **Consistency**: Shared styling and behavior across all components
3. **Interactivity**: Rich user interactions for exploring the timeline
4. **Responsiveness**: Mobile-friendly layouts and adaptive designs
5. **Extensibility**: Easy to add new event types, views, or filters

## Styling Customization

Each component accepts class properties for custom styling. The system uses Tailwind CSS with custom color variables:

- `--primary`: Primary theme color
- `--timeline-primary`: Timeline-specific primary color 
- `--timeline-secondary`: Timeline-specific secondary color

Era-specific styling is provided through the `getEraClasses()` function in TimelineService.

## Future Enhancements

Potential future improvements for the timeline system:

1. **Timeline Branching**: Support for alternate timeline paths
2. **Rich Media**: Embedded images and videos in timeline events
3. **Advanced Filtering**: Search and complex filtering options
4. **Interactive Map**: Full-featured geographic visualization
5. **Timeline Comparison**: Side-by-side comparison of different timelines
