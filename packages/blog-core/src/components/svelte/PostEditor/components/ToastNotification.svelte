<script lang="ts">
import { fade } from 'svelte/transition'

// Props
export const message = ''
export const type: 'success' | 'error' = 'success'
export let show = false
export const duration = 3000 // How long to show the toast (ms)

// Auto-close timer
let timer: number

// Watch for show changes
$: if (show) {
  // Clear any existing timer
  if (timer) clearTimeout(timer)

  // Set timer to auto-hide
  timer = setTimeout(() => {
    show = false
  }, duration)
}

// Clean up on component destruction
import { onDestroy } from 'svelte'
onDestroy(() => {
  if (timer) clearTimeout(timer)
})
</script>
  
  {#if show}
    <div 
      transition:fade={{ duration: 200 }}
      class="fixed top-4 right-4 z-50 p-4 rounded-lg shadow-lg max-w-md {type === 'success' 
        ? 'bg-green-50 text-green-800 border-l-4 border-green-500 dark:bg-green-900/30 dark:text-green-200' 
        : 'bg-red-50 text-red-800 border-l-4 border-red-500 dark:bg-red-900/30 dark:text-red-200'}"
    >
      {message}
    </div>
  {/if}