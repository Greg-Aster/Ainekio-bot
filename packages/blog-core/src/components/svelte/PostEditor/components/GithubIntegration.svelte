<script lang="ts">
import { createEventDispatcher, onMount } from 'svelte'
import GithubAuthForm from '../../admin/GithubAuthForm.svelte'

// Import from .ts files without extension
import { savePostToGitHub, triggerSiteRebuild } from '../utils/githubUtils'

// Use the types correctly with import type
import type { GitHubService, Post } from '../types'

// Initialize event dispatcher
const dispatch = createEventDispatcher<{
  'auth-success': void
  'auth-logout': void
  'save-success': { post: Post; isDraft: boolean }
  'save-error': { error: string }
  'rebuild-success': void
  'rebuild-error': { error: string }
}>()

// Props
export let githubService: GitHubService
export let isGitHubAuthenticated = false
export let showGitHubAuthForm = false
export let isCommitting = false
export let commitStatus: { success: boolean; error: string | null } = {
  success: false,
  error: null,
}
export let showDeployOptions = false
export let githubToken = ''
export let githubFolder = 'src/content/posts'
export let subfolderPath = ''

// Methods
function showGitHubAuth() {
  showGitHubAuthForm = true
}

async function handleGitHubAuth(event: CustomEvent<string> | null) {
  // Get token from event if provided, otherwise use the bound value
  const token = event && event.detail ? event.detail : githubToken

  if (!token) {
    commitStatus.error = 'Please enter a valid token'
    return
  }

  try {
    isCommitting = true
    commitStatus.error = null

    // Authenticate with GitHub
    const success = githubService.authenticate(token)

    if (success) {
      // Test the token with a simple API call
      try {
        await githubService.getFile('README.md')
        isGitHubAuthenticated = true
        showGitHubAuthForm = false
        commitStatus.success = true

        // Show success message
        setTimeout(() => {
          commitStatus.success = false
        }, 3000)

        dispatch('auth-success')
      } catch (error: any) {
        console.error('Token validation error:', error)
        if (error.message && error.message.includes('401')) {
          commitStatus.error =
            'Authentication failed. Please check your token permissions.'
        } else if (error.message && error.message.includes('404')) {
          commitStatus.error =
            'Repository or README.md not found. Check your repository settings.'
        } else {
          commitStatus.error = `Token validation error: ${error.message}`
        }
        githubService.logout() // Clear the invalid token
      }
    } else {
      commitStatus.error = 'Failed to authenticate'
    }
  } catch (error: any) {
    console.error('Authentication error:', error)
    commitStatus.error = error.message || 'Failed to authenticate'
  } finally {
    isCommitting = false
  }
}

function handleGitHubLogout() {
  githubService.logout()
  isGitHubAuthenticated = false
  showDeployOptions = false
  dispatch('auth-logout')
}

async function handleSaveToGitHub(
  event: CustomEvent<{ post: Post; isDraft: boolean }>,
) {
  const { post, isDraft } = event.detail

  try {
    isCommitting = true
    commitStatus.error = null

    const result = await savePostToGitHub(
      post,
      isDraft,
      githubService,
      githubFolder,
      subfolderPath,
    )

    if (result.success) {
      // Update filepath in post if provided
      if (result.filepath) {
        post.filepath = result.filepath
      }

      // Update UI status
      commitStatus.success = true
      showDeployOptions = true

      // Notify parent
      dispatch('save-success', { post, isDraft })

      setTimeout(() => {
        commitStatus.success = false
      }, 3000)
    } else {
      commitStatus.error = result.error
      dispatch('save-error', { error: result.error || 'Unknown error' })
    }
  } catch (error: any) {
    console.error('Error in handleSaveToGitHub:', error)
    commitStatus.error = error.message || 'Unknown error occurred'
    dispatch('save-error', { error: commitStatus.error })
  } finally {
    isCommitting = false
  }
}

async function handleTriggerRebuild() {
  try {
    isCommitting = true
    commitStatus.error = null

    const result = await triggerSiteRebuild(githubService)

    if (result.success) {
      // Update UI status
      commitStatus.success = true
      showDeployOptions = false

      // Notify parent
      dispatch('rebuild-success')

      setTimeout(() => {
        commitStatus.success = false
      }, 3000)
    } else {
      commitStatus.error = result.error
      dispatch('rebuild-error', { error: result.error || 'Unknown error' })
    }
  } catch (error: any) {
    console.error('Error in handleTriggerRebuild:', error)
    commitStatus.error = error.message || 'Unknown error occurred'
    dispatch('rebuild-error', { error: commitStatus.error })
  } finally {
    isCommitting = false
  }
}

// Setup event listener for window events
onMount(() => {
  // Add window event listener for save-to-github
  window.addEventListener('save-to-github', (e: Event) => {
    // TypeScript safe cast
    const customEvent = e as CustomEvent<{ post: Post; isDraft: boolean }>
    if (customEvent.detail) {
      handleSaveToGitHub(customEvent)
    }
  })

  return () => {
    // Remove event listener on component unmount
    window.removeEventListener(
      'save-to-github',
      handleSaveToGitHub as EventListener,
    )
  }
})
</script>

<div class="mb-6">
  {#if !isGitHubAuthenticated}
    <div class="flex items-center justify-between p-3 bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800/30 rounded-md text-blue-800 dark:text-blue-200 mb-4">
      <div class="flex items-center">
        <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 mr-2 flex-shrink-0" viewBox="0 0 24 24">
          <path fill="currentColor" d="M12 .297c-6.63 0-12 5.373-12 12 0 5.303 3.438 9.8 8.205 11.385.6.113.82-.258.82-.577 0-.285-.01-1.04-.015-2.04-3.338.724-4.042-1.61-4.042-1.61C4.422 18.07 3.633 17.7 3.633 17.7c-1.087-.744.084-.729.084-.729 1.205.084 1.838 1.236 1.838 1.236 1.07 1.835 2.809 1.305 3.495.998.108-.776.417-1.305.76-1.605-2.665-.3-5.466-1.332-5.466-5.93 0-1.31.465-2.38 1.235-3.22-.135-.303-.54-1.523.105-3.176 0 0 1.005-.322 3.3 1.23.96-.267 1.98-.399 3-.405 1.02.006 2.04.138 3 .405 2.28-1.552 3.285-1.23 3.285-1.23.645 1.653.24 2.873.12 3.176.765.84 1.23 1.91 1.23 3.22 0 4.61-2.805 5.625-5.475 5.92.42.36.81 1.096.81 2.22 0 1.606-.015 2.896-.015 3.286 0 .315.21.69.825.57C20.565 22.092 24 17.592 24 12.297c0-6.627-5.373-12-12-12" />
        </svg>
        <span>Connect to GitHub to publish posts directly to your repository</span>
      </div>
      <button 
        on:click={showGitHubAuth}
        class="ml-3 py-1 px-3 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium rounded-md transition-colors"
      >
        Connect
      </button>
    </div>
    
    {#if showGitHubAuthForm}
      <GithubAuthForm 
        isAuthenticating={isCommitting}
        errorMessage={commitStatus.error}
        bind:token={githubToken}
        on:authenticate={handleGitHubAuth}
        on:cancel={() => showGitHubAuthForm = false}
        on:error={(e) => commitStatus.error = e.detail}
      />
    {/if}
  {:else}
    <div class="flex items-center justify-between p-3 bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800/30 rounded-md text-green-800 dark:text-green-200">
      <div class="flex items-center">
        <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 mr-2 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
        </svg>
        <span>Connected to GitHub</span>
      </div>
      
      <div class="flex items-center space-x-3">
        <details class="inline-block">
          <summary class="text-sm cursor-pointer hover:underline">Settings</summary>
          <div class="absolute z-10 mt-2 bg-white dark:bg-neutral-800 border border-neutral-200 dark:border-neutral-700 rounded-md shadow-lg p-4 w-64">
            <div class="space-y-3">
              <div>
                <label for="github-folder-inline" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
                  Posts Folder Path
                </label>
                <input 
                  type="text" 
                  id="github-folder-inline" 
                  bind:value={githubFolder} 
                  placeholder="src/content/posts" 
                  class="w-full px-2 py-1 text-sm bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded text-neutral-900 dark:text-neutral-100" 
                />
              </div>
              
              <div>
                <label for="subfolder-path-inline" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
                  Subfolder (Optional)
                </label>
                <input 
                  type="text" 
                  id="subfolder-path-inline" 
                  bind:value={subfolderPath} 
                  placeholder="blog" 
                  class="w-full px-2 py-1 text-sm bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded" 
                />
              </div>
            </div>
          </div>
        </details>
        
        <button 
          on:click={handleGitHubLogout}
          class="py-1 px-3 bg-red-600 hover:bg-red-700 text-white text-sm font-medium rounded-md transition-colors flex items-center"
        >
          Disconnect
        </button>
      </div>
    </div>
    
    {#if commitStatus.success || commitStatus.error}
      <div class="mt-3 {commitStatus.success ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'} text-sm">
        {#if commitStatus.success}
          <div class="flex items-center">
            <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 mr-2" viewBox="0 0 20 20" fill="currentColor">
              <path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd" />
            </svg>
            {showDeployOptions ? 'Post saved to GitHub successfully!' : 'Site rebuild triggered successfully!'}
          </div>
        {:else}
          {commitStatus.error}
        {/if}
      </div>
    {/if}
  {/if}
</div>

<div class="github-action-buttons">
  <slot name="buttons"></slot>
  
  {#if showDeployOptions}
    <button 
      on:click={handleTriggerRebuild}
      disabled={!isGitHubAuthenticated || isCommitting}
      class="px-4 py-2 bg-[var(--primary)] hover:opacity-90 text-white font-medium rounded transition-opacity flex items-center justify-center disabled:opacity-50"
    >
      {#if isCommitting}
        <svg class="animate-spin -ml-1 mr-2 h-4 w-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
        </svg>
        Triggering Rebuild...
      {:else}
        <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 mr-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
        </svg>
        Deploy Site
      {/if}
    </button>
  {/if}
</div>