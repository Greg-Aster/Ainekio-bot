<!-- PageAnimations.svelte -->
<script lang="ts">
import { onMount } from 'svelte'

onMount(() => {
  // Initialize page load animations
  initializeOnloadAnimations()
  initializePostImageAnimation()
})

function initializeOnloadAnimations() {
  const elements = document.querySelectorAll('.onload-animation')
  elements.forEach((element, index) => {
    setTimeout(
      () => {
        element.classList.add('loaded')
      },
      100 + index * 50,
    )
  })
}

function initializePostImageAnimation() {
  const postImage = document.getElementById('post-image')
  if (postImage) {
    setTimeout(() => {
      postImage.classList.remove('opacity-0', 'scale-105')
    }, 100)
  }
}
</script>

<!-- This component handles animations but doesn't render anything -->
<div style="display: none;"></div>