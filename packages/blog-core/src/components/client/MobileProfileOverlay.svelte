<!-- MobileProfileOverlay.svelte -->
<script lang="ts">
import { onMount } from 'svelte'
import Profile from './Profile.svelte'

export let postSlug = ''
export let customAvatar = ''
export let customName = ''
export let customBio = ''
export let profileConfig: any = {}
export let avatarConfig: any = {}

let isVisible = false
let overlayElement: HTMLDivElement
let profileButton: HTMLElement | null = null

onMount(() => {
  // Add a small delay to ensure DOM is fully ready
  const initializeOverlay = () => {
    profileButton = document.getElementById('sidenav-profile-btn')

    // Listen for profile toggle events
    const handleProfileToggle = () => {
      isVisible = !isVisible
      if (isVisible) {
        // Use requestAnimationFrame to ensure positioning happens after render
        requestAnimationFrame(() => {
          positionOverlay()
        })
      }
    }

    document.addEventListener('profile:toggle', handleProfileToggle)

    return () => {
      document.removeEventListener('profile:toggle', handleProfileToggle)
    }
  }

  // Small delay to ensure DOM is ready
  const timeoutId = setTimeout(initializeOverlay, 100)

  return () => {
    clearTimeout(timeoutId)
  }
})

function positionOverlay() {
  if (!profileButton || !overlayElement) return

  try {
    const buttonRect = profileButton.getBoundingClientRect()
    const overlayWidth = overlayElement.offsetWidth
    const screenWidth = window.innerWidth
    const screenHeight = window.innerHeight

    let left = buttonRect.left - overlayWidth - 8
    let top = buttonRect.top

    // Adjust if overlay goes off screen
    if (left < 8) {
      left = buttonRect.right + 8
    }

    if (left + overlayWidth > screenWidth - 8) {
      left = screenWidth - overlayWidth - 8
    }

    if (top + overlayElement.offsetHeight > screenHeight - 8) {
      top = screenHeight - overlayElement.offsetHeight - 8
    }

    if (top < 8) {
      top = 8
    }

    overlayElement.style.left = `${left}px`
    overlayElement.style.top = `${top}px`
  } catch (error) {
    console.warn('Error positioning profile overlay:', error)
  }
}

function closeOverlay() {
  isVisible = false
}

function handleClickOutside(event: MouseEvent) {
  const target = event.target as Element

  if (
    isVisible &&
    !overlayElement?.contains(target) &&
    !target.closest('#unified-sidenav')
  ) {
    closeOverlay()
  }
}

function handleKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape' && isVisible) {
    closeOverlay()
  }
}

function handleResize() {
  if (isVisible) {
    positionOverlay()
  }
}
</script>

<svelte:window 
  on:click={handleClickOutside} 
  on:keydown={handleKeydown}
  on:resize={handleResize}
/>

<div 
  bind:this={overlayElement}
  class="fixed z-[60] md:hidden transition-all duration-300"
  class:opacity-0={!isVisible}
  class:translate-y-4={!isVisible}
  class:pointer-events-none={!isVisible}
  class:opacity-100={isVisible}
  class:translate-y-0={isVisible}
  style="width: 17.5rem;"
>
  <div class="p-2">
    <div class="card-base p-3 shadow-xl">
      <div class="flex justify-end mb-2">
        <button 
          on:click={closeOverlay}
          aria-label="Close Profile" 
          class="btn-plain rounded-full w-6 h-6 flex items-center justify-center text-sm hover:bg-black/10 dark:hover:bg-white/10"
        >
          ✕
        </button>
      </div>
      <div id="mobile-profile-content">
        <Profile 
          slug={postSlug}
          customAvatar={customAvatar}
          customName={customName}
          customBio={customBio}
          isHomePage={false}
          profileConfig={profileConfig}
          avatarConfig={avatarConfig}
        />
      </div>
    </div>
  </div>
</div>
