<script>
import { onMount } from 'svelte'
import { profileConfig, siteConfig } from '@/config/config'
import {
  addFriend,
  addPermanentFriends,
  downloadFriendAsMarkdown,
  fetchFriendContent,
  formatUrl,
  friends,
  getFriends,
  initFriendsFromStorage,
  removeFriend,
  updateFriend,
  validateSite,
} from '@/stores/friendStore'

// Props
export let savedFriends = []

// Form inputs
let friendName = ''
let friendUrl = ''
let friendContentEnabled = true
let lastSyncTime = null

// Status message for UI feedback
let statusMessage = ''
let statusType = 'info'
let isLoading = false

// Sync states
let syncStates = {}
let syncAllStatus = 'idle'


// Check if an image exists
async function checkImageExists(url) {
  return new Promise(resolve => {
    const img = new Image()
    img.onload = () => resolve(true)
    img.onerror = () => resolve(false)
    img.src = url
  })
}

// Image error handler with improved retry logic for static sites
function handleImageError(event) {
  try {
    const originalSrc = event.target.src
    console.log(`Avatar image failed to load: ${originalSrc}`)

    // Prevent infinite error loops
    if (originalSrc.includes('/assets/avatar/avatar.png')) {
      console.log('Default avatar failed to load, using fallback SVG')
      event.target.src =
        "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E%3Ccircle cx='50' cy='50' r='50' fill='%23d1d5db'/%3E%3C/svg%3E"
      event.target.onerror = null
      return
    }

    // Try to load the default avatar with correct path for GitHub Pages
    const basePath = document.querySelector('base')?.getAttribute('href') || ''
    event.target.src = `${basePath}/assets/avatar/avatar.png`.replace('//', '/')

    // Set fallback for default avatar
    event.target.onerror = () => {
      event.target.src =
        "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E%3Ccircle cx='50' cy='50' r='50' fill='%23d1d5db'/%3E%3C/svg%3E"
      event.target.onerror = null
    }
  } catch (error) {
    console.error('Error in image error handler:', error)
    // Final fallback
    try {
      event.target.src =
        "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E%3Ccircle cx='50' cy='50' r='50' fill='%23d1d5db'/%3E%3C/svg%3E"
      event.target.onerror = null
    } catch {
      // Last resort - hide the image
      if (event.target.style) {
        event.target.style.display = 'none'
      }
    }
  }
}

// Initialize client-side settings (all browser API access deferred to onMount)
onMount(() => {
  // Initialize localStorage persistence — must run in browser to avoid hydration mismatch
  initFriendsFromStorage()

  // Load permanent friends from git content after storage is initialized
  if (savedFriends && savedFriends.length > 0) {
    addPermanentFriends(savedFriends)
  }

  friendContentEnabled =
    localStorage.getItem('friendContentEnabled') !== 'false'
  lastSyncTime = localStorage.getItem('lastFriendSyncTime')
})

function showStatus(message, type = 'info', autoDismiss = true) {
  statusMessage = message
  statusType = type

  if (autoDismiss) {
    setTimeout(() => {
      statusMessage = ''
    }, 5000)
  }
}

// Add a new friend
async function addNewFriend() {
  if (!friendUrl) {
    showStatus('Please provide a URL for the friend site.', 'error')
    return
  }

  const cleanUrl = formatUrl(friendUrl)

  if (getFriends().some(f => f.url === cleanUrl)) {
    showStatus('This site is already in your friends list.', 'error')
    return
  }

  isLoading = true
  showStatus('Validating site and fetching content...', 'info', false)

  try {
    const validation = await validateSite(cleanUrl)

    if (!validation.valid) {
      showStatus(`Site validation failed: ${validation.message}`, 'error')
      isLoading = false
      return
    }

    let siteName = friendName || validation.siteInfo?.name
    const siteBio = validation.siteInfo?.description || ''
    const siteAvatar = validation.siteInfo?.avatar || ''

    if (!siteName) {
      try {
        const url = new URL(cleanUrl)
        siteName = url.hostname.replace('www.', '')
      } catch {
        siteName = cleanUrl
      }
    }

    const newFriend = {
      id: `friend-${Date.now()}`,
      name: siteName,
      url: cleanUrl,
      bio: siteBio,
      avatar: siteAvatar,
      postCount: 0,
      lastSynced: null,
      posts: [],
      isPermanent: false,
    }

    addFriend(newFriend)
    friendName = ''
    friendUrl = ''

    try {
      const posts = await fetchFriendContent(cleanUrl)
      updateFriend({
        ...newFriend,
        posts,
        postCount: posts.length,
        lastSynced: new Date().toISOString(),
      })
      showStatus(
        `Friend added successfully with ${posts.length} posts!`,
        'success',
      )
    } catch (error) {
      console.error('Error fetching content:', error)
      showStatus('Friend added, but error fetching content.', 'error')
    }
  } catch (error) {
    console.error('Error adding friend:', error)
    showStatus(`Error: ${error.message}`, 'error')
  } finally {
    isLoading = false
  }
}

function handleRemoveFriend(id) {
  if (confirm('Are you sure you want to remove this friend?')) {
    removeFriend(id)
  }
}

function handleSaveAsPermanent(friend) {
  try {
    const { filename } = downloadFriendAsMarkdown(friend)
    showStatus(
      `File "${filename}" created! Move to content/friends/`,
      'success',
    )
  } catch (error) {
    console.error('Error saving friend:', error)
    showStatus(`Error creating file: ${error.message}`, 'error')
  }
}

async function syncFriend(friend) {
  syncStates = { ...syncStates, [friend.id]: 'syncing' }

  try {
    const posts = await fetchFriendContent(friend.url)
    updateFriend({
      ...friend,
      posts,
      postCount: posts.length,
      lastSynced: new Date().toISOString(),
    })
    syncStates = { ...syncStates, [friend.id]: 'success' }
  } catch (error) {
    console.error('Error syncing friend content:', error)
    syncStates = { ...syncStates, [friend.id]: 'error' }
  } finally {
    setTimeout(() => {
      const { [friend.id]: _, ...rest } = syncStates
      syncStates = rest
    }, 2000)
  }
}

async function syncAllFriends() {
  const allFriends = getFriends()
  if (allFriends.length === 0) {
    alert('No friends to sync. Add some friends first.')
    return
  }

  syncAllStatus = 'syncing'

  try {
    for (const friend of allFriends) {
      try {
        const posts = await fetchFriendContent(friend.url)
        updateFriend({
          ...friend,
          posts,
          postCount: posts.length,
          lastSynced: new Date().toISOString(),
        })
      } catch (error) {
        console.error(`Error syncing friend ${friend.name}:`, error)
      }
    }

    const now = new Date().toISOString()
    localStorage.setItem('lastFriendSyncTime', now)
    lastSyncTime = now
    syncAllStatus = 'success'
  } catch (error) {
    console.error('Error in global sync:', error)
    syncAllStatus = 'error'
  } finally {
    setTimeout(() => {
      syncAllStatus = 'idle'
    }, 2000)
  }
}

function updateContentIntegration(event) {
  friendContentEnabled = event.target.checked
  localStorage.setItem('friendContentEnabled', friendContentEnabled)
  document.dispatchEvent(
    new CustomEvent('friend-content-toggled', {
      detail: { enabled: friendContentEnabled },
      bubbles: true,
    }),
  )
}

function formatTimeAgo(dateString) {
  if (!dateString) return 'Never'
  const date = new Date(dateString)
  const now = new Date()
  const diffMs = now - date
  const diffSec = Math.floor(diffMs / 1000)
  const diffMin = Math.floor(diffSec / 60)
  const diffHour = Math.floor(diffMin / 60)
  const diffDay = Math.floor(diffHour / 24)

  if (diffDay > 0) return diffDay === 1 ? 'yesterday' : `${diffDay} days ago`
  if (diffHour > 0) return `${diffHour} hour${diffHour === 1 ? '' : 's'} ago`
  if (diffMin > 0) return `${diffMin} minute${diffMin === 1 ? '' : 's'} ago`
  return 'just now'
}
</script>

<!-- Status message display -->
{#if statusMessage}
<div class={`mb-4 p-3 rounded-md text-sm 
    ${statusType === 'info' ? 'bg-blue-50 text-blue-600 dark:bg-blue-900 dark:text-blue-400' : ''}
    ${statusType === 'success' ? 'bg-green-50 text-green-600 dark:bg-green-900 dark:text-green-400' : ''}
    ${statusType === 'error' ? 'bg-red-50 text-red-600 dark:bg-red-900 dark:text-red-400' : ''}`}>
    <div class="flex items-start">
      {#if statusType === 'info'}
        <svg xmlns="http://www.w3.org/2000/svg" class="w-5 h-5 mr-2 flex-shrink-0" viewBox="0 0 20 20" fill="currentColor">
          <path fill-rule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z" clip-rule="evenodd" />
        </svg>
      {:else if statusType === 'success'}
        <svg xmlns="http://www.w3.org/2000/svg" class="w-5 h-5 mr-2 flex-shrink-0" viewBox="0 0 20 20" fill="currentColor">
          <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd" />
        </svg>
      {:else if statusType === 'error'}
        <svg xmlns="http://www.w3.org/2000/svg" class="w-5 h-5 mr-2 flex-shrink-0" viewBox="0 0 20 20" fill="currentColor">
          <path fill-rule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7 4a1 1 0 11-2 0 1 1 0 012 0zm-1-9a1 1 0 00-1 1v4a1 1 0 102 0V6a1 1 0 00-1-1z" clip-rule="evenodd" />
        </svg>
      {/if}
      <div>{statusMessage}</div>
    </div>
</div>
{/if}

<!-- Add New Friend Section -->
<div class="mb-6 bg-neutral-50 dark:bg-neutral-800/50 p-4 rounded-lg">
  <h3 class="text-md font-medium text-black/70 dark:text-white/70 mb-3">Add New Friend</h3>
  <div class="grid grid-cols-1 gap-4">
    <div>
      <label for="friend-url" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">Friend Site URL</label>
      <div class="flex">
        <input 
          type="url" 
          id="friend-url" 
          bind:value={friendUrl}
          placeholder="https://friendsite.com"
          class="flex-1 px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-l-md text-sm text-neutral-800 dark:text-neutral-200 transition" 
          disabled={isLoading}
        />
        <button 
          on:click={addNewFriend}
          disabled={isLoading}
          class="px-4 py-2 bg-[var(--primary)] text-white font-medium rounded-r-md hover:opacity-90 transition-opacity flex items-center justify-center disabled:opacity-60"
        >
          {#if isLoading}
            <svg xmlns="http://www.w3.org/2000/svg" class="w-5 h-5 animate-spin mr-2" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <circle cx="12" cy="12" r="10"></circle>
              <path d="M12 6v6l4 2"></path>
            </svg>
            Processing...
          {:else}
            <svg xmlns="http://www.w3.org/2000/svg" class="w-5 h-5 mr-2" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"></path>
              <circle cx="8.5" cy="7" r="4"></circle>
              <line x1="20" y1="8" x2="20" y2="14"></line>
              <line x1="23" y1="11" x2="17" y2="11"></line>
            </svg>
            Add Friend
          {/if}
        </button>
      </div>
      <p class="text-xs text-neutral-500 dark:text-neutral-400 mt-1">
        Enter a friend site URL to add it. Information will be automatically fetched if available.
      </p>
    </div>
  </div>
</div>

<!-- Unified Friends List -->
<div class="space-y-6">
  <h3 class="text-xl font-medium text-black/80 dark:text-white/80 mb-2">All Friends</h3>
  <p class="text-sm text-neutral-500 dark:text-neutral-400 mb-4">Manage all your friends in one place. Permanent friends (green background) are stored in your site content, while temporary friends are stored in your browser.</p>
  
  {#if $friends.length === 0}
    <div class="p-8 text-center bg-neutral-50 dark:bg-neutral-800/20 rounded-lg">
      <svg xmlns="http://www.w3.org/2000/svg" class="w-12 h-12 mx-auto text-neutral-400 dark:text-neutral-600 mb-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"></path>
        <circle cx="9" cy="7" r="4"></circle>
        <path d="M23 21v-2a4 4 0 0 0-3-3.87"></path>
        <path d="M16 3.13a4 4 0 0 1 0 7.75"></path>
      </svg>
      <h3 class="text-lg font-medium text-neutral-700 dark:text-neutral-300 mb-2">No Friends Yet</h3>
      <p class="text-sm text-neutral-500 dark:text-neutral-400 mb-4">Add a site URL using the form above to start sharing content.</p>
    </div>
  {:else}
    <div class="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
      {#each $friends as friend (friend.id)}
        <div class={`friend-card flex items-start p-4 border border-neutral-200 dark:border-neutral-700 rounded-lg hover:border-[var(--primary)] transition-colors ${friend.isPermanent ? 'bg-green-50 dark:bg-green-900/10' : ''}`} 
             data-friend-id={friend.id}>
             <div class="w-12 h-12 bg-neutral-200 dark:bg-neutral-700 rounded-full overflow-hidden mr-4 flex-shrink-0">
              {#if typeof friend.avatar === 'string' && friend.avatar.trim() !== ''}
                <img 
                  src={friend.avatar} 
                  alt={`${friend.name}'s avatar`}
                  class="w-full h-full object-cover"
                  on:error={handleImageError}
                />
              {:else}
                <img 
                  src="/assets/avatar/avatar.png" 
                  alt={`${friend.name}'s avatar`}
                  class="w-full h-full object-cover"
                  on:error={handleImageError}
                />
              {/if}
            </div>
          <div class="flex-1">
            <h3 class="text-lg font-medium text-black/80 dark:text-white/80 mb-1">
              {friend.name}
              {#if friend.isPermanent}
                <span class="inline-block ml-2 px-2 py-0.5 text-xs bg-green-100 dark:bg-green-800 text-green-800 dark:text-green-100 rounded-full">Permanent</span>
              {/if}
            </h3>
            <p class="text-sm text-neutral-500 dark:text-neutral-400 mb-2">
              {friend.bio || 'No bio provided'}
            </p>
            <div class="flex items-center text-xs text-neutral-500 dark:text-neutral-400">
              <a href={friend.url} target="_blank" rel="noopener noreferrer" class="text-xs text-[var(--primary)] hover:underline flex items-center mr-3">
                <svg xmlns="http://www.w3.org/2000/svg" class="w-4 h-4 mr-1" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"></path>
                  <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"></path>
                </svg>
                Visit Site
              </a>
              <span class="flex items-center mr-3">
                <svg xmlns="http://www.w3.org/2000/svg" class="w-4 h-4 mr-1" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
                  <polyline points="14 2 14 8 20 8"></polyline>
                  <line x1="16" y1="13" x2="8" y2="13"></line>
                  <line x1="16" y1="17" x2="8" y2="17"></line>
                  <polyline points="10 9 9 9 8 9"></polyline>
                </svg>
                <span>{friend.postCount || 0} Posts</span>
              </span>
              <span class="flex items-center">
                <svg xmlns="http://www.w3.org/2000/svg" class="w-4 h-4 mr-1" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <circle cx="12" cy="12" r="10"></circle>
                  <polyline points="12 6 12 12 16 14"></polyline>
                </svg>
                <span>{formatTimeAgo(friend.lastSynced)}</span>
              </span>
            </div>
          </div>
          <div class="flex flex-col flex-shrink-0 ml-2 gap-2">
            <button 
              on:click={() => syncFriend(friend)}
              class="friend-sync p-2 text-[var(--primary)] hover:bg-[var(--primary)] hover:bg-opacity-10 rounded-full" 
              title="Sync content"
              disabled={syncStates[friend.id] === 'syncing'}
            >
              {#if syncStates[friend.id] === 'syncing'}
                <svg xmlns="http://www.w3.org/2000/svg" class="w-5 h-5 animate-spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38"></path>
                </svg>
              {:else if syncStates[friend.id] === 'success'}
                <svg xmlns="http://www.w3.org/2000/svg" class="w-5 h-5 text-green-500" viewBox="0 0 20 20" fill="currentColor">
                  <path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd" />
                </svg>
              {:else if syncStates[friend.id] === 'error'}
                <svg xmlns="http://www.w3.org/2000/svg" class="w-5 h-5 text-red-500" viewBox="0 0 20 20" fill="currentColor">
                  <path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd" />
                </svg>
              {:else}
                <svg xmlns="http://www.w3.org/2000/svg" class="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38"></path>
                </svg>
              {/if}
            </button>
            
            {#if !friend.isPermanent}
              <button 
                on:click={() => handleSaveAsPermanent(friend)}
                class="p-2 text-green-500 hover:bg-green-500 hover:bg-opacity-10 rounded-full" 
                title="Save as permanent friend"
              >
                <svg xmlns="http://www.w3.org/2000/svg" class="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"></path>
                  <polyline points="17 21 17 13 7 13 7 21"></polyline>
                  <polyline points="7 3 7 8 15 8"></polyline>
                </svg>
              </button>
            {/if}
            
            {#if !friend.isPermanent}
              <button 
                on:click={() => handleRemoveFriend(friend.id)}
                class="p-2 text-red-500 hover:bg-red-500 hover:bg-opacity-10 rounded-full" 
                title="Remove friend"
              >
                <svg xmlns="http://www.w3.org/2000/svg" class="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <polyline points="3 6 5 6 21 6"></polyline>
                  <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
                  <line x1="10" y1="11" x2="10" y2="17"></line>
                  <line x1="14" y1="11" x2="14" y2="17"></line>
                </svg>
              </button>
            {/if}
          </div>
        </div>
      {/each}
    </div>
  {/if}
</div>

<!-- Content Integration Controls -->
<div class="bg-neutral-50 dark:bg-neutral-800/50 p-4 rounded-lg">
  <h3 class="text-md font-medium text-black/70 dark:text-white/70 mb-3">Content Integration</h3>
  <div class="flex items-center mb-4">
    <input 
      type="checkbox" 
      id="enable-friend-content" 
      checked={friendContentEnabled}
      on:change={updateContentIntegration}
      class="mr-3" 
    />
    <div>
      <label for="enable-friend-content" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300">Enable Friend Content in Main Feed</label>
      <p class="text-xs text-neutral-500 dark:text-neutral-400">When enabled, your friends' posts will appear in your main feed while you're logged in</p>
    </div>
  </div>
  <div class="flex items-center justify-between">
    <button 
      id="sync-all-button"
      on:click={syncAllFriends}
      disabled={$friends.length === 0 || isLoading}
      class="px-4 py-2 bg-[var(--primary)] text-white font-medium rounded-md hover:opacity-90 transition-opacity flex items-center justify-center disabled:opacity-60"
    >
      {#if syncAllStatus === 'syncing'}
        <svg xmlns="http://www.w3.org/2000/svg" class="w-5 h-5 animate-spin mr-2" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="12" cy="12" r="10"></circle>
          <path d="M12 6v6l4 2"></path>
        </svg>
        Syncing...
      {:else if syncAllStatus === 'success'}
        <svg xmlns="http://www.w3.org/2000/svg" class="w-5 h-5 text-green-500 mr-2" viewBox="0 0 20 20" fill="currentColor">
          <path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd" />
        </svg>
        Sync Complete
      {:else if syncAllStatus === 'error'}
        <svg xmlns="http://www.w3.org/2000/svg" class="w-5 h-5 text-red-500 mr-2" viewBox="0 0 20 20" fill="currentColor">
          <path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd" />
        </svg>
        Sync Failed
      {:else}
        <svg xmlns="http://www.w3.org/2000/svg" class="w-5 h-5 mr-2" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M22 12c0-5.52-4.48-10-10-10s-10 4.48-10 10 4.48 10 10 10 10-4.48 10-10"></path>
          <path d="M12 2v10l4 4"></path>
        </svg>
        Sync All Friends
      {/if}
    </button>
    <div class="text-sm text-neutral-500 dark:text-neutral-400">
      Last global sync: {lastSyncTime ? formatTimeAgo(lastSyncTime) : 'Never'}
    </div>
  </div>
</div>
