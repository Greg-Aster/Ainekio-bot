<!-- Profile.svelte - Enhanced with video playback controls -->
<script lang="ts">
import { onDestroy, onMount } from 'svelte'

// Props
export let slug = ''
export let customAvatar = ''
export let customName = ''
export let customBio = ''
export let customLink = ''
export let isHomePage = false
export let profileConfig: any
export let avatarConfig: any

interface RuntimeAuthorContext {
  slug: string
  customAvatar: string
  customName: string
  customBio: string
  customLink: string
  isHomePage: boolean
}

function normalizeBaseUrl(path: string): string {
  if (!path) return ''
  if (
    path.startsWith('http://') ||
    path.startsWith('https://') ||
    path.startsWith('//') ||
    path.startsWith('data:')
  ) {
    return path
  }

  const baseUrl = (import.meta.env.BASE_URL || '/').replace(/\/$/, '')

  if (!path.startsWith('/')) return path
  if (baseUrl && path.startsWith(`${baseUrl}/`)) return path

  const normalizedBase = import.meta.env.BASE_URL || '/'
  const trimmedBase = normalizedBase.endsWith('/')
    ? normalizedBase.slice(0, -1)
    : normalizedBase

  return `${trimmedBase}${path}`.replace(/\/+/g, '/')
}

// 🎬 NEW: Extended HTMLVideoElement type to support custom properties
interface ExtendedHTMLVideoElement extends HTMLVideoElement {
  endedHandler?: () => void
}

// State
let currentAvatarIndex = 0
let animationDirection = 1
let animationTimer: number | null = null
let videoElements: ExtendedHTMLVideoElement[] = [] // 🎬 NEW: Track video elements
let videoElement: ExtendedHTMLVideoElement // 🎬 NEW: Single video element binding
let runtimeAuthorContext: RuntimeAuthorContext | null = null

// 🎬 NEW: Video configuration from avatarConfig
$: videoConfig = avatarConfig?.videoConfig || {}
$: playbackRate = videoConfig.playbackRate || 0.5 // Default to 50% speed
$: shouldLoop = videoConfig.loop ?? true // Default to true, can be disabled
$: loopDelay = videoConfig.loopDelay || 5000 // Delay between loops in ms
$: playOnce = videoConfig.playOnce || false // Play once then stop

// 🎬 NEW: Animated file detection
function isAnimatedFile(src: string): boolean {
  if (!src) return false
  const lowercaseSrc = src.toLowerCase()
  return (
    lowercaseSrc.includes('.gif') ||
    lowercaseSrc.includes('.webp') ||
    lowercaseSrc.includes('.apng') ||
    lowercaseSrc.match(/\.(gif|webp|apng)(\?|$)/)
  )
}

// 🎬 NEW: Video file detection
function isVideoFile(src: string): boolean {
  if (!src) return false
  const lowercaseSrc = src.toLowerCase()
  return (
    lowercaseSrc.includes('.mp4') ||
    lowercaseSrc.includes('.webm') ||
    lowercaseSrc.includes('.mov') ||
    lowercaseSrc.match(/\.(mp4|webm|mov|avi)(\?|$)/)
  )
}

// Computed values
$: effectiveSlug = runtimeAuthorContext?.slug ?? slug
$: effectiveCustomAvatar = runtimeAuthorContext?.customAvatar ?? customAvatar
$: effectiveCustomName = runtimeAuthorContext?.customName ?? customName
$: effectiveCustomBio = runtimeAuthorContext?.customBio ?? customBio
$: effectiveCustomLink = runtimeAuthorContext?.customLink ?? customLink
$: effectiveIsHomePage = runtimeAuthorContext?.isHomePage ?? isHomePage

$: useDefaultAvatars = !effectiveCustomAvatar
$: displayName = effectiveCustomName || profileConfig?.name || 'Author'
$: displayBio = effectiveCustomBio || profileConfig?.bio || ''
$: displayLink = normalizeBaseUrl(effectiveCustomLink || '/about/')
$: socialLinks = profileConfig?.links || []

// Avatar selection logic
$: activeAvatarIndex = (() => {
  if (effectiveIsHomePage || !useDefaultAvatars) return 0
  return getAvatarIndexFromSlug(effectiveSlug, avatarConfig?.avatarList?.length || 1)
})()

$: selectedAvatar = (() => {
  if (!useDefaultAvatars) return effectiveCustomAvatar
  if (effectiveIsHomePage && avatarConfig?.homeAvatar) {
    return typeof avatarConfig.homeAvatar === 'string'
      ? avatarConfig.homeAvatar
      : avatarConfig.homeAvatar.src || avatarConfig.homeAvatar
  }
  if (avatarConfig?.avatarList?.length > 0) {
    const avatar = avatarConfig.avatarList[activeAvatarIndex]
    return typeof avatar === 'string' ? avatar : avatar.src || avatar
  }
  return ''
})()

$: avatarList = (() => {
  if (!avatarConfig?.avatarList) return []
  return avatarConfig.avatarList.map(avatar =>
    typeof avatar === 'string' ? avatar : avatar.src || avatar,
  )
})()

$: hasAnimatedAvatar = useDefaultAvatars
  ? effectiveIsHomePage
    ? isAnimatedFile(selectedAvatar)
    : avatarList.some(src => isAnimatedFile(src))
  : isAnimatedFile(effectiveCustomAvatar)

$: hasMultipleAvatars =
  useDefaultAvatars &&
  avatarList.length > 1 &&
  !effectiveIsHomePage &&
  !hasAnimatedAvatar

function syncAuthorContextFromDOM() {
  const contextElement = document.getElementById('author-context')
  if (!(contextElement instanceof HTMLElement)) return

  runtimeAuthorContext = {
    slug: contextElement.dataset.slug || '',
    customAvatar: contextElement.dataset.customAvatar || '',
    customName: contextElement.dataset.customName || '',
    customBio: contextElement.dataset.customBio || '',
    customLink: contextElement.dataset.customLink || '',
    isHomePage: contextElement.dataset.isHomePage === 'true',
  }
}

function getAvatarIndexFromSlug(slug: string, arrayLength: number): number {
  if (!slug || arrayLength === 0) return 0

  let hash = 0
  for (let i = 0; i < slug.length; i++) {
    const char = slug.charCodeAt(i)
    hash = (hash << 5) - hash + char
    hash = hash & hash
  }
  return Math.abs(hash) % arrayLength
}

// 🎬 NEW: Configure video element with custom settings
function configureVideoElement(video: HTMLVideoElement) {
  if (!video) return

  if (import.meta.env.DEV) {
    console.log('🎬 Configuring video element:', {
      playbackRate,
      shouldLoop,
      loopDelay,
      playOnce,
      videoSrc: video.src,
    })
  }

  // Set playback rate
  video.playbackRate = playbackRate
  if (import.meta.env.DEV) {
    console.log('🎬 Video playback rate set to:', video.playbackRate)
  }

  // Remove any existing event listeners to prevent duplicates
  if (video.endedHandler) {
    video.removeEventListener('ended', video.endedHandler)
  }

  // Handle loop behavior
  if (playOnce) {
    video.loop = false
    video.endedHandler = () => {
      video.pause()
    }
    video.addEventListener('ended', video.endedHandler)
  } else if (loopDelay > 0) {
    video.loop = false
    video.endedHandler = () => {
      setTimeout(() => {
        if (video && video.paused) {
          video.currentTime = 0
          video.play().catch(e => {
            if (import.meta.env.DEV) {
              console.log('Video play failed:', e)
            }
          })
        }
      }, loopDelay)
    }
    video.addEventListener('ended', video.endedHandler)
  } else {
    video.loop = shouldLoop
    video.endedHandler = null
  }

  // Add to tracking array if not already present
  if (!videoElements.includes(video)) {
    videoElements.push(video)
    if (import.meta.env.DEV) {
      console.log(
        '🎬 Added video to tracking array. Total videos:',
        videoElements.length,
      )
    }
  }
}

// 🎬 NEW: Update all video elements when config changes
function updateVideoSettings() {
  if (import.meta.env.DEV) {
    console.log('🎬 Updating video settings for', videoElements.length, 'videos')
  }
  videoElements.forEach((video: ExtendedHTMLVideoElement) => {
    if (video && !video.paused) {
      if (import.meta.env.DEV) {
        console.log('🎬 Updating video:', video.src, 'to rate:', playbackRate)
      }
      video.playbackRate = playbackRate
      video.loop = shouldLoop && loopDelay === 0 && !playOnce
    }
  })
}

// Watch for config changes and update videos
// Only update if we actually have video elements to configure
$: {
  if ((playbackRate || shouldLoop || loopDelay || playOnce) && videoElements.length > 0) {
    if (import.meta.env.DEV) {
      console.log('🎬 Video config changed:', {
        playbackRate,
        shouldLoop,
        loopDelay,
        playOnce,
        videoElementsCount: videoElements.length,
      })
    }
    updateVideoSettings()
  }
}

function startAvatarAnimation() {
  if (!hasMultipleAvatars || !avatarList.length) return

  currentAvatarIndex = activeAvatarIndex

  animationTimer = setInterval(() => {
    currentAvatarIndex += animationDirection

    if (currentAvatarIndex >= avatarList.length) {
      currentAvatarIndex = avatarList.length - 1
      animationDirection = -1
    }
    if (currentAvatarIndex < 0) {
      currentAvatarIndex = 0
      animationDirection = 1
    }
  }, avatarConfig?.animationInterval || 3500)
}

function stopAvatarAnimation() {
  if (animationTimer) {
    clearInterval(animationTimer)
    animationTimer = null
  }
}

// 🎬 NEW: Render media component with video configuration
function renderMediaElement(
  src: string,
  alt: string,
  className: string,
  loading = 'eager',
) {
  const normalizedSrc = normalizeBaseUrl(src)

  if (isVideoFile(normalizedSrc)) {
    return {
      type: 'video',
      src: normalizedSrc,
      alt,
      className,
      loading,
      playbackRate,
      shouldLoop: shouldLoop && loopDelay === 0 && !playOnce,
      playOnce,
      loopDelay,
    }
  }
  return { type: 'image', src: normalizedSrc, alt, className, loading }
}

onMount(() => {
  // Initialize currentAvatarIndex to the selected avatar
  currentAvatarIndex = activeAvatarIndex

  // Debug logging (only if we have valid config)
  if (import.meta.env.DEV && (avatarConfig || profileConfig)) {
    console.log('Profile component mounted:', {
      slug,
      useDefaultAvatars,
      hasMultipleAvatars,
      hasAnimatedAvatar,
      avatarListLength: avatarList.length,
      selectedAvatar: selectedAvatar || 'none',
      activeAvatarIndex,
      currentAvatarIndex,
      profileName: displayName,
      customLink: displayLink,
      videoConfig: {
        // 🎬 NEW: Log video configuration
        playbackRate,
        shouldLoop,
        loopDelay,
        playOnce,
      },
    })
  }

  if (hasMultipleAvatars) {
    startAvatarAnimation()
  }
})

onMount(() => {
  const handleAuthorContext = (event: Event) => {
    const customEvent = event as CustomEvent<RuntimeAuthorContext>
    if (!customEvent?.detail) return
    runtimeAuthorContext = customEvent.detail
  }

  syncAuthorContextFromDOM()
  window.addEventListener('merkin:author-context', handleAuthorContext)
  document.addEventListener('astro:page-load', syncAuthorContextFromDOM)

  return () => {
    window.removeEventListener('merkin:author-context', handleAuthorContext)
    document.removeEventListener('astro:page-load', syncAuthorContextFromDOM)
  }
})

onDestroy(() => {
  stopAvatarAnimation()
  // 🎬 NEW: Clean up video elements properly
  videoElements.forEach((video: ExtendedHTMLVideoElement) => {
    if (video) {
      video.pause()
      // Remove custom event listeners
      if (video.endedHandler) {
        video.removeEventListener('ended', video.endedHandler)
      }
      video.removeAttribute('src')
      video.load()
    }
  })
  videoElements = []
})

// Handle navigation changes (Astro page transitions)
onMount(() => {
  const handlePageLoad = () => {
    stopAvatarAnimation()
    if (hasMultipleAvatars) {
      setTimeout(startAvatarAnimation, 100)
    }
  }

  document.addEventListener('astro:page-load', handlePageLoad)
  return () => {
    document.removeEventListener('astro:page-load', handlePageLoad)
  }
})
</script>

<div class="card-base p-3">
  <a
    aria-label="Go to About Page"
    href={displayLink}
    class="group block relative mx-auto mt-1 md:mx-0 md:mt-0 mb-3 max-w-[12rem] md:max-w-none overflow-hidden rounded-xl active:scale-95"
  >
    <div class="absolute transition pointer-events-none group-hover:bg-black/30 group-active:bg-black/50 w-full h-full z-50 flex items-center justify-center">
      <svg 
        class="transition opacity-0 scale-90 group-hover:scale-100 group-hover:opacity-100 text-white w-12 h-12"
        fill="none" 
        stroke="currentColor" 
        viewBox="0 0 24 24"
      >
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" 
              d="M10 6H5a2 2 0 00-2 2v9a2 2 0 002 2h14a2 2 0 002-2V8a2 2 0 00-2-2h-5m-4 0V4a2 2 0 114 0v2m-4 0a2 2 0 104 0m-5 8a2 2 0 100-4 2 2 0 000 4zm0 0c1.306 0 2.417.835 2.83 2M9 14a3.001 3.001 0 00-2.83 2M15 11h3m-3 4h2" />
      </svg>
    </div>

    <!-- Image container with relative positioning -->
    <div class="relative w-full aspect-square">
      {#if useDefaultAvatars}
        {#if effectiveIsHomePage || !hasMultipleAvatars}
          <!-- Single avatar (home page, single avatar, or animated avatar) -->
          {#if selectedAvatar}
            {@const mediaConfig = renderMediaElement(selectedAvatar, "Profile Image of the Site Owner", "avatar-image w-full h-full object-contain opacity-100 rounded-xl", "eager")}
            
            {#if mediaConfig.type === 'video'}
              <!-- 🎬 ENHANCED: Video avatar with custom controls -->
              <video
                bind:this={videoElement}
                src={mediaConfig.src}
                class={mediaConfig.className}
                autoplay
                muted
                loop={mediaConfig.shouldLoop}
                playsinline
                disablePictureInPicture
                preload="auto"
                on:loadedmetadata={(e) => configureVideoElement(e.currentTarget as ExtendedHTMLVideoElement)}
              >
                <!-- Fallback for unsupported video -->
                <div class="avatar-image w-full h-full flex items-center justify-center bg-gradient-to-br from-blue-400 to-purple-500 rounded-xl">
                  <svg class="w-16 h-16 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"></path>
                  </svg>
                </div>
              </video>
            {:else}
              <!-- Image avatar (includes animated GIFs, WebP, etc.) -->
              <img
                src={mediaConfig.src}
                alt={mediaConfig.alt}
                class={mediaConfig.className}
                loading={mediaConfig.loading}
              />
            {/if}
          {:else}
            <!-- Fallback avatar placeholder -->
            <div class="avatar-image w-full h-full flex items-center justify-center bg-gradient-to-br from-blue-400 to-purple-500 rounded-xl">
              <svg class="w-16 h-16 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"></path>
              </svg>
            </div>
          {/if}
        {:else}
          <!-- Multiple avatars with animation -->
          {#each avatarList as src, index}
            {#if src}
              {@const mediaConfig = renderMediaElement(src, "Profile Image of the Author", `avatar-image absolute inset-0 w-full h-full object-contain transition-opacity duration-1000 rounded-xl ${index === currentAvatarIndex ? 'opacity-100' : 'opacity-0'}`, index === activeAvatarIndex ? 'eager' : 'lazy')}
              
              {#if mediaConfig.type === 'video'}
                <!-- 🎬 ENHANCED: Video in cycling mode with controls -->
                <video
                  src={mediaConfig.src}
                  class={mediaConfig.className}
                  autoplay={index === currentAvatarIndex}
                  muted
                  loop={mediaConfig.shouldLoop}
                  playsinline
                  disablePictureInPicture
                  preload={mediaConfig.loading === 'eager' ? 'auto' : 'none'}
                  on:loadedmetadata={(e) => configureVideoElement(e.currentTarget as ExtendedHTMLVideoElement)}
                ></video>
              {:else}
                <!-- Static image in cycling mode -->
                <img
                  src={mediaConfig.src}
                  alt={mediaConfig.alt}
                  class={mediaConfig.className}
                  loading={mediaConfig.loading}
                />
              {/if}
            {/if}
          {/each}
        {/if}
      {:else}
        <!-- Custom avatar -->
        {#if effectiveCustomAvatar}
          {@const mediaConfig = renderMediaElement(effectiveCustomAvatar, `Profile Image of ${displayName}`, "avatar-image w-full h-full object-contain opacity-100 rounded-xl", "eager")}
          
          {#if mediaConfig.type === 'video'}
            <!-- 🎬 ENHANCED: Custom video avatar with controls -->
            <video
              bind:this={videoElement}
              src={mediaConfig.src}
              class={mediaConfig.className}
              autoplay
              muted
              loop={mediaConfig.shouldLoop}
              playsinline
              disablePictureInPicture
              preload="auto"
              on:loadedmetadata={(e) => configureVideoElement(e.currentTarget as ExtendedHTMLVideoElement)}
            >
              <!-- Fallback for unsupported video -->
              <div class="avatar-image w-full h-full flex items-center justify-center bg-gradient-to-br from-blue-400 to-purple-500 rounded-xl">
                <svg class="w-16 h-16 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"></path>
                </svg>
              </div>
            </video>
          {:else}
            <!-- Custom image avatar -->
            <img
              src={mediaConfig.src}
              alt={mediaConfig.alt}
              class={mediaConfig.className}
              loading={mediaConfig.loading}
            />
          {/if}
        {:else}
          <!-- Fallback avatar placeholder -->
          <div class="avatar-image w-full h-full flex items-center justify-center bg-gradient-to-br from-blue-400 to-purple-500 rounded-xl">
            <svg class="w-16 h-16 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"></path>
            </svg>
          </div>
        {/if}
      {/if}
    </div>
  </a>

   <div class="px-2">
    <div class="font-bold text-xl text-center mb-1 dark:text-neutral-50 transition">
      {displayName}
    </div>
    <div class="h-1 w-5 bg-[var(--primary)] mx-auto rounded-full mb-2 transition"></div>
    <div class="text-center text-neutral-400 mb-2.5 transition">
      {displayBio}
    </div> 
    
    <!-- Social Links -->
    <!-- {#if socialLinks.length > 0}
      <div class="flex gap-2 justify-center mb-1">
        {#if socialLinks.length > 1}
          {#each socialLinks as link}
            <a
              rel="me"
              aria-label={link.name}
              href={link.url}
              target="_blank"
              class="btn-regular rounded-lg h-10 w-10 active:scale-90 flex items-center justify-center"
            > -->
              <!-- Social icon SVGs -->
              <!-- {#if link.icon.includes('github')}
                <svg class="w-6 h-6" fill="currentColor" viewBox="0 0 24 24">
                  <path d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z"/>
                </svg>
              {:else if link.icon.includes('twitter')}
                <svg class="w-6 h-6" fill="currentColor" viewBox="0 0 24 24">
                  <path d="M23.953 4.57a10 10 0 01-2.825.775 4.958 4.958 0 002.163-2.723c-.951.555-2.005.959-3.127 1.184a4.92 4.92 0 00-8.384 4.482C7.69 8.095 4.067 6.13 1.64 3.162a4.822 4.822 0 00-.666 2.475c0 1.71.87 3.213 2.188 4.096a4.904 4.904 0 01-2.228-.616v.06a4.923 4.923 0 003.946 4.827 4.996 4.996 0 01-2.212.085 4.936 4.936 0 004.604 3.417 9.867 9.867 0 01-6.102 2.105c-.39 0-.779-.023-1.17-.067a13.995 13.995 0 007.557 2.209c9.053 0 13.998-7.496 13.998-13.985 0-.21 0-.42-.015-.63A9.935 9.935 0 0024 4.59z"/>
                </svg>
              {:else if link.icon.includes('linkedin')}
                <svg class="w-6 h-6" fill="currentColor" viewBox="0 0 24 24">
                  <path d="M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433c-1.144 0-2.063-.926-2.063-2.065 0-1.138.92-2.063 2.063-2.063 1.14 0 2.064.925 2.064 2.063 0 1.139-.925 2.065-2.064 2.065zm1.782 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z"/>
                </svg>
              {:else if link.icon.includes('mail') || link.icon.includes('email')}
                <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 8l7.89 4.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"/>
                </svg>
              {:else} -->
                <!-- Generic link icon for unknown types -->
                <!-- <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1"/>
                </svg>
              {/if}
            </a>
          {/each}
        {:else} -->
          <!-- Single link with label -->
          <!-- <a
            rel="me"
            aria-label={socialLinks[0].name}
            href={socialLinks[0].url}
            target="_blank"
            class="btn-regular rounded-lg h-10 gap-2 px-3 font-bold active:scale-95 flex items-center"
          >
            {#if socialLinks[0].icon.includes('github')}
              <svg class="w-6 h-6" fill="currentColor" viewBox="0 0 24 24">
                <path d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z"/>
              </svg>
            {:else} -->
              <!-- Other single link icons... -->
              <!-- <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1"/>
              </svg>
            {/if}
            {socialLinks[0].name}
          </a>
        {/if}
      </div>
    {/if} -->
  </div>
</div>

<style>
  .avatar-image {
    border-radius: 0.75rem;
  }
  
  /* Ensure smooth transitions */
  .transition-opacity {
    transition: opacity 1s ease-in-out;
  }

  /* Ensure videos fit properly */
  video.avatar-image {
    object-fit: cover;
  }
</style>
