<!-- ScrollEffects.svelte -->
<script lang="ts">
import { onMount } from 'svelte'

export let bannerConfig: any
export let siteConfig: any

let ticking = false
let parallaxImage: HTMLElement | null = null
let tocWrapper: HTMLElement | null = null

onMount(() => {
  syncDomRefs()

  // Set transparency if configured
  if (siteConfig?.transparency) {
    document.documentElement.style.setProperty(
      '--bg-opacity',
      siteConfig.transparency.toString(),
    )
  }

  // Scroll listener for parallax and TOC
  const handleScroll = () => {
    if (!ticking) {
      requestAnimationFrame(updateEffects)
      ticking = true
    }
  }

  window.addEventListener('scroll', handleScroll)
  window.addEventListener('load', handleParallaxLoad)
  document.addEventListener('astro:page-load', handlePageLoad)

  if (document.readyState === 'complete') {
    handleParallaxLoad()
  }

  return () => {
    window.removeEventListener('scroll', handleScroll)
    window.removeEventListener('load', handleParallaxLoad)
    document.removeEventListener('astro:page-load', handlePageLoad)
  }
})

function syncDomRefs() {
  parallaxImage = document.getElementById('parallax-image')
  tocWrapper = document.querySelector('#toc-wrapper')
}

function handlePageLoad() {
  syncDomRefs()
  handleParallaxLoad()
  updateEffects()
}

function updateEffects() {
  const scrollY = window.scrollY

  // Update parallax effect
  if (parallaxImage && bannerConfig?.parallax?.scrollFactor) {
    const offset = scrollY * bannerConfig.parallax.scrollFactor
    parallaxImage.style.transform = `translate3d(0, ${offset}px, 0)`
  }

  // Update TOC visibility
  if (tocWrapper) {
    tocWrapper.classList.remove('toc-hide')
  }

  ticking = false
}

function handleParallaxLoad() {
  const parallaxBanner = document.getElementById('parallax-banner')
  if (parallaxBanner) {
    setTimeout(() => {
      parallaxBanner.classList.add('loaded')
    }, 100)
  }
}
</script>

<!-- This component handles scroll effects but doesn't render anything -->
<div style="display: none;"></div>
