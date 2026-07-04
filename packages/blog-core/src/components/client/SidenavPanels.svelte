<!-- SidenavPanels.svelte -->
<script lang="ts">
import { onMount } from 'svelte'

export let siteConfig: any

let currentHue = 230
let showInlineHueSlider = false
let showMenuPanel = false
let showSettingsPanel = false
let isFullscreen = false
let menuPanel: HTMLElement
let settingsPanel: HTMLElement

onMount(() => {
  // Add a small delay to ensure DOM is fully ready
  const initialize = () => {
    try {
      // Initialize hue from localStorage
      currentHue = Number.parseInt(localStorage.getItem('hue') || '230')
      setHue(currentHue)

      // Initialize theme
      const savedTheme = localStorage.getItem('theme')
      if (savedTheme === 'dark') {
        document.documentElement.classList.add('dark')
      }

      // Fullscreen listener
      const updateFullscreenState = () => {
        isFullscreen = !!document.fullscreenElement
      }
      document.addEventListener('fullscreenchange', updateFullscreenState)
      updateFullscreenState()

      // Connect to SideNavbar buttons
      connectToSideNavbarButtons()

      return () => {
        document.removeEventListener('fullscreenchange', updateFullscreenState)
      }
    } catch (error) {
      console.warn('Error initializing SidenavPanels:', error)
      return () => {}
    }
  }

  const timeoutId = setTimeout(initialize, 100)

  return () => {
    clearTimeout(timeoutId)
  }
})

// Reactive positioning when panels open
$: if (showMenuPanel && menuPanel) {
  const menuToggleBtn = document.getElementById('sidenav-menu-toggle')
  if (menuToggleBtn) {
    setTimeout(() => positionPanelRelativeToButton('menu', menuToggleBtn), 10)
  }
}

$: if (showSettingsPanel && settingsPanel) {
  const settingsToggleBtn = document.getElementById('sidenav-settings-toggle')
  if (settingsToggleBtn) {
    setTimeout(
      () => positionPanelRelativeToButton('settings', settingsToggleBtn),
      10,
    )
  }
}

function setHue(newHue: number) {
  currentHue = newHue
  localStorage.setItem('hue', newHue.toString())
  document.documentElement.style.setProperty('--hue', newHue.toString())
}

function resetHue() {
  setHue(230)
}

function toggleTheme() {
  const isDark = document.documentElement.classList.toggle('dark')
  localStorage.setItem('theme', isDark ? 'dark' : 'light')
}

function toggleFullscreen() {
  try {
    if (!document.fullscreenElement) {
      document.documentElement.requestFullscreen()
    } else {
      document.exitFullscreen()
    }
  } catch (error) {
    console.warn('Fullscreen toggle failed:', error)
  }
}

function openSearch() {
  try {
    const searchPanel = document.getElementById('search-panel')
    if (searchPanel) {
      closeAllPanels()
      searchPanel.classList.toggle('float-panel-closed')

      const searchInput = searchPanel.querySelector('input[type="search"]')
      if (
        searchInput &&
        !searchPanel.classList.contains('float-panel-closed')
      ) {
        setTimeout(() => (searchInput as HTMLInputElement).focus(), 100)
      }
    }
  } catch (error) {
    console.warn('Search panel toggle failed:', error)
  }
}

function closeAllPanels() {
  showMenuPanel = false
  showSettingsPanel = false
  showInlineHueSlider = false
}

function handleClickOutside(event: MouseEvent) {
  const target = event.target as Element
  if (
    !target.closest('.sidenav-panel') &&
    !target.closest('#sidenav-menu-toggle') &&
    !target.closest('#sidenav-settings-toggle') &&
    !target.closest('[data-panel-trigger]')
  ) {
    closeAllPanels()
  }
}

function handleKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') {
    closeAllPanels()
  }
}

// Timeline toggle function
function toggleTimelineBanner() {
  const current = localStorage.getItem('defaultBannerType') || 'standard'
  localStorage.setItem(
    'defaultBannerType',
    current === 'timeline' ? 'standard' : 'timeline',
  )
  window.location.reload()
}

// Connect to the actual SideNavbar buttons
function connectToSideNavbarButtons() {
  const menuToggleBtn = document.getElementById('sidenav-menu-toggle')
  const settingsToggleBtn = document.getElementById('sidenav-settings-toggle')
  const timelineBtn = document.getElementById('sidenav-timeline-btn')

  if (menuToggleBtn) {
    menuToggleBtn.addEventListener('click', e => {
      e.stopPropagation()
      showSettingsPanel = false
      showMenuPanel = !showMenuPanel
    })
  }

  if (settingsToggleBtn) {
    settingsToggleBtn.addEventListener('click', e => {
      e.stopPropagation()
      showMenuPanel = false
      showSettingsPanel = !showSettingsPanel
    })
  }

  if (timelineBtn) {
    timelineBtn.addEventListener('click', e => {
      e.stopPropagation()
      toggleTimelineBanner()
    })
  }
}

// Position panels relative to their trigger buttons
function positionPanelRelativeToButton(
  panelType: 'menu' | 'settings',
  button: HTMLElement,
) {
  const panel = panelType === 'menu' ? menuPanel : settingsPanel

  if (!panel || !button) return

  const buttonRect = button.getBoundingClientRect()
  const panelWidth = panel.offsetWidth
  const screenWidth = window.innerWidth
  const screenHeight = window.innerHeight

  let left = buttonRect.right + 8 // Start to the right of the button
  let top = buttonRect.top

  // Adjust if panel goes off screen
  if (left + panelWidth > screenWidth - 8) {
    left = buttonRect.left - panelWidth - 8 // Move to left side of button
  }

  if (left < 8) {
    left = 8 // Don't go off left edge
  }

  if (top + panel.offsetHeight > screenHeight - 8) {
    top = screenHeight - panel.offsetHeight - 8
  }

  if (top < 8) {
    top = 8
  }

  panel.style.left = `${left}px`
  panel.style.top = `${top}px`
}
</script>

<svelte:window on:click={handleClickOutside} on:keydown={handleKeydown} />

<!-- Menu Panel -->
{#if showMenuPanel}
  <div class="sidenav-panel fixed z-[100] card-base shadow-lg rounded-lg w-48 md:w-56 panel-open" bind:this={menuPanel}>
    <div class="p-2">
      <div class="text-xs font-medium text-center mb-2 text-neutral-400 px-2">Navigation</div>
      
      <!-- Archive and About Links (Priority) -->
      <div class="flex flex-col gap-1 mb-3 border-b border-black/10 dark:border-white/10 pb-2">
        <a href="/archive/" class="nav-menu-link btn-plain rounded-md px-3 py-2.5 text-sm font-medium active:scale-95 transition-all duration-200 flex items-center gap-2 text-left w-full">
          <svg class="w-4 h-4 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 8h14M5 8a2 2 0 110-4h14a2 2 0 110 4M5 8v10a2 2 0 002 2h10a2 2 0 002-2V8m-9 4h4"></path>
          </svg>
          <span class="flex-1 min-w-0 truncate">Archive</span>
        </a>
        <a href="/about/" class="nav-menu-link btn-plain rounded-md px-3 py-2.5 text-sm font-medium active:scale-95 transition-all duration-200 flex items-center gap-2 text-left w-full">
          <svg class="w-4 h-4 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"></path>
          </svg>
          <span class="flex-1 min-w-0 truncate">About</span>
        </a>
      </div>
      
      <!-- All Other Links -->
      <div class="flex flex-col gap-1">
        <a href="/" class="nav-menu-link btn-plain rounded-md px-3 py-2.5 text-sm font-medium active:scale-95 transition-all duration-200 flex items-center gap-2 text-left w-full">
          <svg class="w-4 h-4 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6"></path>
          </svg>
          <span class="flex-1 min-w-0 truncate">Home</span>
        </a>
        <a href="/projects/" class="nav-menu-link btn-plain rounded-md px-3 py-2.5 text-sm font-medium active:scale-95 transition-all duration-200 flex items-center gap-2 text-left w-full">
          <svg class="w-4 h-4 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 13.255A23.931 23.931 0 0112 15c-3.183 0-6.22-.62-9-1.745M16 6V4a2 2 0 00-2-2h-4a2 2 0 00-2-2v2m8 0H8m8 0v2a2 2 0 01-2 2H10a2 2 0 01-2-2V6"></path>
          </svg>
          <span class="flex-1 min-w-0 truncate">Projects</span>
        </a>
        <a href="/posts/" class="nav-menu-link btn-plain rounded-md px-3 py-2.5 text-sm font-medium active:scale-95 transition-all duration-200 flex items-center gap-2 text-left w-full">
          <svg class="w-4 h-4 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"></path>
          </svg>
          <span class="flex-1 min-w-0 truncate">Blog</span>
        </a>
        <a href="/timeline/" class="nav-menu-link btn-plain rounded-md px-3 py-2.5 text-sm font-medium active:scale-95 transition-all duration-200 flex items-center gap-2 text-left w-full">
          <svg class="w-4 h-4 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"></path>
          </svg>
          <span class="flex-1 min-w-0 truncate">Timeline</span>
        </a>
        <a href="/cookbook/" class="nav-menu-link btn-plain rounded-md px-3 py-2.5 text-sm font-medium active:scale-95 transition-all duration-200 flex items-center gap-2 text-left w-full">
          <svg class="w-4 h-4 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253"></path>
          </svg>
          <span class="flex-1 min-w-0 truncate">Cookbook</span>
        </a>
      </div>
    </div>
  </div>
{/if}

<!-- Settings Panel -->
{#if showSettingsPanel}
  <div class="sidenav-panel fixed z-[100] card-base shadow-lg rounded-lg w-48 md:w-56 panel-open" bind:this={settingsPanel}>
    <div class="p-2">
      <div class="text-xs font-medium text-center mb-2 text-neutral-400 px-2">Settings</div>
      <div class="flex flex-col gap-1">
        
        <!-- SEARCH BUTTON -->
        <button 
          on:click={openSearch}
          class="btn-plain rounded-md px-3 py-2.5 text-sm font-medium active:scale-95 transition-all duration-200 flex items-center gap-2 text-left w-full"
        >
          <svg class="w-4 h-4 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"></path>
          </svg>
          <span class="flex-1 min-w-0 truncate">Search</span>
        </button>
        
        <!-- THEME TOGGLE -->
        <button 
          on:click={toggleTheme}
          class="btn-plain rounded-md px-3 py-2.5 text-sm font-medium active:scale-95 transition-all duration-200 flex items-center gap-2 text-left w-full"
        >
          <svg class="w-4 h-4 flex-shrink-0 dark:hidden" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z"></path>
          </svg>
          <svg class="w-4 h-4 flex-shrink-0 hidden dark:block" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z"></path>
          </svg>
          <span class="flex-1 min-w-0 truncate">Theme</span>
        </button>
        
        <!-- FULLSCREEN TOGGLE -->
        <button 
          on:click={toggleFullscreen}
          class="btn-plain rounded-md px-3 py-2.5 text-sm font-medium active:scale-95 transition-all duration-200 items-center gap-2 text-left w-full hidden md:flex"
        >
          {#if !isFullscreen}
            <svg class="w-4 h-4 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 8V4m0 0h4M4 4l5 5m11-1V4m0 0h-4m4 0l-5 5M4 16v4m0 0h4m-4 0l5-5m11 5l-5-5m5 5v-4m0 4h-4"></path>
            </svg>
          {:else}
            <svg class="w-4 h-4 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 9V4.5M9 9H4.5M9 9L3.5 3.5M15 9v4.5M15 9h4.5M15 9l5.5-5.5M9 15v4.5M9 15H4.5M9 15l-5.5 5.5M15 15v4.5m0-4.5h4.5m-4.5 0l5.5 5.5"></path>
            </svg>
          {/if}
          <span class="flex-1 min-w-0 truncate">Fullscreen</span>
        </button>
        
        <!-- DISPLAY SETTINGS (HUE SLIDER) -->
        {#if !siteConfig?.themeColor?.fixed}
          <button 
            on:click={() => showInlineHueSlider = !showInlineHueSlider}
            data-panel-trigger
            class="btn-plain rounded-md px-3 py-2.5 text-sm font-medium active:scale-95 transition-all duration-200 flex items-center gap-2 text-left w-full"
          >
            <svg class="w-4 h-4 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 21a4 4 0 01-4-4V5a2 2 0 012-2h4a2 2 0 012 2v12a4 4 0 01-4 4zM21 5H9a2 2 0 00-2 2v12a4 4 0 004 4h10a2 2 0 002-2V7a2 2 0 00-2-2z"></path>
            </svg>
            <span class="flex-1 min-w-0 truncate">Colors</span>
          </button>
          
          <!-- INLINE HUE SLIDER -->
          {#if showInlineHueSlider}
            <div class="mt-1 px-2 py-2 bg-[var(--card-bg)] rounded-md border border-black/10 dark:border-white/10">
              <div class="flex items-center justify-between gap-1 mb-2 text-xs">
                <span class="font-medium text-neutral-600 dark:text-neutral-400 flex-shrink-0">Hue</span>
                <div class="bg-[var(--btn-regular-bg)] text-[var(--btn-content)] px-1 py-1 rounded text-xs font-bold min-w-[1.5rem] text-center flex-shrink-0">
                  {currentHue}
                </div>
                <button 
                  on:click={resetHue}
                  aria-label="Reset Hue" 
                  class="btn-plain rounded px-1 py-1 text-xs active:scale-90 flex-shrink-0"
                >
                  <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"></path>
                  </svg>
                </button>
              </div>
              <div class="w-full flex justify-center">
                <div class="w-6 h-24 rounded relative overflow-hidden hue-gradient">
                  <input 
                    type="range" 
                    bind:value={currentHue}
                    on:input={(e) => setHue(parseInt(e.target.value))}
                    min="0" 
                    max="360" 
                    step="5"
                    orient="vertical"
                    class="absolute inset-0 w-full h-full opacity-0 cursor-pointer hue-slider"
                    aria-label="Theme Hue"
                  />
                  <div 
                    class="absolute left-0 w-full h-0.5 bg-white border border-black/30 rounded-sm pointer-events-none shadow-sm hue-thumb"
                    style="top: calc((360 - {currentHue})/360 * 100% - 1px)"
                  ></div>
                </div>
              </div>
            </div>
          {/if}
        {/if}
      </div>
    </div>
  </div>
{/if}

<style>
  .hue-gradient {
    background: linear-gradient(to bottom, 
      hsl(360, 100%, 50%), 
      hsl(300, 100%, 50%), 
      hsl(240, 100%, 50%), 
      hsl(180, 100%, 50%), 
      hsl(120, 100%, 50%), 
      hsl(60, 100%, 50%), 
      hsl(0, 100%, 50%));
  }
  
  .hue-slider {
    writing-mode: bt-lr; 
    -webkit-appearance: slider-vertical;
  }
  
  .sidenav-panel.panel-open {
    @apply opacity-100 translate-x-0 pointer-events-auto;
  }
</style>