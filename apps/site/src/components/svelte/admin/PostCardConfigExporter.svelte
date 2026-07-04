<script>
    import { createEventDispatcher, onMount } from 'svelte';
    import { fade } from 'svelte/transition';
    
    // Props
    export let show = false;
    export let postCardConfig;
    
    // Local state
    let copySuccess = false;
    let tsConfig = '';
    
    // Event dispatcher
    const dispatch = createEventDispatcher();
    
    // Format config as TypeScript
    function formatAsTypeScript() {
      return `// Configuration for PostCard components and friend post integration
  
  // Base PostCard configuration
  export interface PostCardConfig {
    // Layout options
    layout: {
      imagePosition: 'right' | 'top'; // Position of the image
      imageSizePercentage: number; // Size as percentage (e.g., 28 for 28%)
      cardBorderRadius: string; // Border radius for the card
      showEnterButton: boolean; // Whether to show the enter button
    };
    // Styling options
    styling: {
      titleSize: string; // Title font size class
      descriptionLines: number; // Number of lines to show in description
      animationEnabled: boolean; // Whether to enable load animations
    };
    // Content display options
    content: {
      showCategory: boolean;
      showTags: boolean;
      showUpdateDate: boolean;
      showWordCount: boolean;
      showReadTime: boolean;
      hideTagsOnMobile: boolean;
    };
  }
  
  // Friend post specific configuration
  export interface FriendPostConfig {
    // Styling to differentiate friend posts
    styling: {
      indicatorType: 'border' | 'badge' | 'background'; // How to visually indicate friend posts
      indicatorColor: string; // Color for the indicator
      showFriendAvatar: boolean; // Whether to show friend's avatar
      avatarSize: string; // Size of the avatar
    };
    // Attribution options
    attribution: {
      showAttribution: boolean; // Whether to show attribution
      attributionText: string; // Text template for attribution
      linkToFriendSite: boolean; // Whether to link to friend's site
    };
    // Integration behavior
    behavior: {
      sortingMethod: 'date' | 'source'; // How to sort mixed posts
      mergeWithLocalPosts: boolean; // Whether to merge with local posts or show separately
    };
  }
  
  // Combined configuration
  export interface PostCardConfigs {
    localPosts: PostCardConfig;
    friendPosts: PostCardConfig & FriendPostConfig;
  }
  
  // Export the configuration
  export const postCardConfig: PostCardConfigs = ${JSON.stringify(postCardConfig, null, 2)};`;
    }
    
    // Copy config to clipboard
    async function copyToClipboard() {
      try {
        await navigator.clipboard.writeText(tsConfig);
        copySuccess = true;
        setTimeout(() => copySuccess = false, 2000);
      } catch (error) {
        console.error('Failed to copy config to clipboard', error);
        alert('Failed to copy to clipboard. Please try again.');
      }
    }
    
    // Update TS config when props change
    $: if (postCardConfig) {
      tsConfig = formatAsTypeScript();
    }
    
    // Handle close event
    function handleClose() {
      dispatch('close');
    }
  </script>
  
  {#if show}
    <div transition:fade={{ duration: 200 }} class="fixed inset-0 bg-black/50 dark:bg-black/60 z-50 flex items-center justify-center overflow-y-auto" on:click|self={handleClose}>
      <div class="bg-white dark:bg-neutral-800 rounded-lg max-w-4xl w-full m-4 overflow-auto shadow-lg">
        <div class="p-6">
          <div class="flex justify-between items-center mb-4">
            <h2 class="text-xl font-bold text-black/90 dark:text-white/90">Post Card Configuration</h2>
            <button 
              on:click={handleClose}
              class="text-neutral-500 hover:text-neutral-800 dark:hover:text-neutral-300"
            >
              <svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
          
          <div class="text-sm text-neutral-600 dark:text-neutral-400 mb-4">
            <p>Below is the TypeScript configuration for your post cards. You can copy this code to your <code>src/config/postcard.config.ts</code> file.</p>
          </div>
          
          <div class="relative">
            <pre class="bg-neutral-100 dark:bg-neutral-900 p-4 rounded-lg border border-neutral-200 dark:border-neutral-700 overflow-x-auto text-sm font-mono text-neutral-800 dark:text-neutral-300 h-96">{tsConfig}</pre>
            
            <div class="absolute top-2 right-2">
              <button 
                on:click={copyToClipboard}
                class="py-1.5 px-3 bg-neutral-200 dark:bg-neutral-700 hover:bg-neutral-300 dark:hover:bg-neutral-600 rounded-md transition-colors text-sm flex items-center"
                title="Copy to clipboard"
              >
                {#if copySuccess}
                  <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 mr-1.5" viewBox="0 0 20 20" fill="currentColor">
                    <path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd" />
                  </svg>
                  Copied!
                {:else}
                  <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 mr-1.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
                  </svg>
                  Copy
                {/if}
              </button>
            </div>
          </div>
          
          <div class="mt-6 flex justify-end">
            <button 
              on:click={handleClose}
              class="py-2 px-4 bg-[var(--primary)] hover:opacity-90 text-white font-medium rounded-md transition-opacity"
            >
              Close
            </button>
          </div>
        </div>
      </div>
    </div>
  {/if}