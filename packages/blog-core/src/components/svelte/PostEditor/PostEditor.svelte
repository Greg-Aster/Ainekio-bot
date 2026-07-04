<script lang="ts">
import { onMount } from 'svelte'
import { createGitHubService } from '../../../lib/github-service'

import GithubIntegration from './components/GithubIntegration.svelte'
import ImportPanel from './components/ImportPanel.svelte'
import PostBrowser from './components/PostBrowser.svelte'
import PostForm from './components/PostForm.svelte'
// Import components
import ToastNotification from './components/ToastNotification.svelte'

// Import utility functions correctly
import {
  createEmptyPost,
  generateFrontmatter,
  getCachedPosts,
  saveCachedPost,
} from './utils/postUtils'

// Use import type for TypeScript interfaces
import type { Post, PostMetadata } from './utils/postUtils'

import { fetchGitHubPosts, initializeGithubService } from './utils/githubUtils'

import type { GitHubService } from './utils/githubUtils'

import { generateMdxFile } from './utils/fileUtils'

import type { FileImportResult } from './utils/fileUtils'

// Tab state
let activeTab: 'create' | 'import' | 'browse' = 'create'

// GitHub integration state
let githubService: GitHubService = createGitHubService()
let isGitHubAuthenticated = false
let showGitHubAuthForm = false
let isCommitting = false
let commitStatus = { success: false, error: null as string | null }
let showDeployOptions = false
let githubToken = ''
let githubFolder = 'src/content/posts'
let subfolderPath = ''

// Local posts browsing state
let localPosts: PostMetadata[] = []
let isLoadingPosts = false
let loadError: string | null = null
let selectedPost: string | null = null
let isEditing = false
let isDeleting = false

// Cached posts for faster loading
let cachedPosts: PostMetadata[] = []

// Post model
let post: Post = createEmptyPost()

// Toast notification state
let showToast = false
let toastMessage = ''
let toastType: 'success' | 'error' = 'success'

// Derived values
$: formValid = !!post.title && !!post.slug && !!post.published

// Initialize GitHub service
function initializeGithub() {
  const initResult = initializeGithubService(githubService)
  isGitHubAuthenticated = initResult.isGitHubAuthenticated
  loadError = initResult.loadError

  // Set GitHub repository settings if needed
  if (!githubService.config) {
    githubService = createGitHubService({
      // These should match your GitHub repository details
      owner: 'your-github-username', // Update with your GitHub username
      repo: 'your-repo-name', // Update with your repository name
      branch: 'main', // Update with your branch name
      configPath: 'src/config',
      postsPath: githubFolder,
    })
  }
}

// Toast notification function
function showNotification(
  message: string,
  type: 'success' | 'error' = 'success',
) {
  toastMessage = message
  toastType = type
  showToast = true

  setTimeout(() => {
    showToast = false
  }, 3000)
}

// Save draft
async function saveDraft() {
  await savePost(true)
}

// Publish post
async function publishPost() {
  await savePost(false)
}

// Common save function
async function savePost(isDraft = false) {
  try {
    post.draft = isDraft

    // Build complete post data
    const postData = { ...post }

    // Convert comma-separated tags to array if it's a string
    if (typeof postData.tags === 'string') {
      postData.tags = postData.tags
        ? postData.tags.split(',').map(tag => tag.trim())
        : []
    }

    // Generate and download the MDX file
    generateMdxFile(postData)

    // Save to localStorage for future reference
    const updatedCachedPosts = saveCachedPost(postData, githubFolder)
    cachedPosts = updatedCachedPosts

    // Show success toast
    showNotification(
      isDraft ? 'Draft saved successfully!' : 'Post published successfully!',
    )
  } catch (error: any) {
    console.error('Error saving post:', error)
    showNotification('Failed to save post: ' + error.message, 'error')
  }
}

// Fetch local posts
async function fetchLocalPosts() {
  isLoadingPosts = true
  loadError = null

  try {
    // Try to get posts from GitHub if authenticated
    if (isGitHubAuthenticated) {
      try {
        const posts = await fetchGitHubPosts(githubService, githubFolder)
        localPosts = posts

        // Save these posts to localStorage for future reference
        localStorage.setItem('cachedPosts', JSON.stringify(posts))
        cachedPosts = posts

        return
      } catch (error: any) {
        console.error('Failed to fetch posts from GitHub:', error)
        loadError =
          'Failed to load posts from GitHub. Falling back to cached posts.'

        // Fall back to localStorage cache
        localPosts = getCachedPosts()
        return
      }
    } else {
      // Not authenticated with GitHub, use localStorage cache
      const cached = getCachedPosts()
      if (cached.length > 0) {
        localPosts = cached
      } else {
        loadError =
          'No cached posts found. Please authenticate with GitHub to load posts.'
        localPosts = []
      }
    }
  } catch (error: any) {
    console.error('Error fetching posts:', error)
    loadError = 'Failed to load posts: ' + error.message
    localPosts = []
  } finally {
    isLoadingPosts = false
  }
}

// Load post for editing
async function loadPostForEditing(postId: string) {
  try {
    let postData: Partial<Post> | null = null

    // First try to get the full post data from localStorage
    const cachedFullPost = localStorage.getItem(
      `fullPost_${postId.replace(/\.(md|mdx)$/, '')}`,
    )

    if (cachedFullPost) {
      // We have the full post in localStorage
      postData = JSON.parse(cachedFullPost)
    } else if (isGitHubAuthenticated) {
      // If using GitHub, get the content from the repository
      const selectedPost = localPosts.find(p => p.id === postId)
      if (!selectedPost) {
        throw new Error('Post not found')
      }

      const filepath = selectedPost.filepath
      const file = await githubService.getFile(filepath)

      // Import parseMdxFile function
      const { parseMdxFile } = await import('./utils/postUtils')
      const { frontmatter, content } = parseMdxFile(file.content)

      // Create a full post object
      postData = {
        title: frontmatter.title || selectedPost.title,
        description: frontmatter.description || selectedPost.description || '',
        slug: selectedPost.slug,
        published:
          frontmatter.published ||
          selectedPost.published ||
          new Date().toISOString().split('T')[0],
        image: frontmatter.image || '',
        tags: Array.isArray(frontmatter.tags)
          ? frontmatter.tags.join(', ')
          : frontmatter.tags || '',
        category: frontmatter.category || selectedPost.category || '',
        draft: frontmatter.draft === undefined ? false : frontmatter.draft,
        content: content,
        filepath: filepath,
        advanced: {
          avatarImage: frontmatter.avatarImage || '',
          authorName: frontmatter.authorName || '',
          authorBio: frontmatter.authorBio || '',
          showImageOnPost:
            frontmatter.showImageOnPost === undefined
              ? false
              : (frontmatter.showImageOnPost as boolean),
          lang: frontmatter.lang || 'en',
          bannerImage: frontmatter.bannerImage || '',
        },
        timelineData: {
          enabled: !!(
            frontmatter.timelineYear ||
            frontmatter.timelineEra ||
            frontmatter.timelineLocation
          ),
          year: frontmatter.timelineYear,
          era: frontmatter.timelineEra || '',
          location: frontmatter.timelineLocation || '',
          isKeyEvent: frontmatter.isKeyEvent || false,
        },
        banner: {
          type: frontmatter.bannerType || '',
          videoId: frontmatter.bannerData?.videoId || '',
          timelineCategory: frontmatter.bannerData?.category || '',
        },
      }

      // Save this full post to localStorage for future use
      localStorage.setItem(
        `fullPost_${postData.slug}`,
        JSON.stringify(postData),
      )
    } else {
      // Can't get the full post
      throw new Error(
        'Could not load the full post. Try authenticating with GitHub.',
      )
    }

    if (!postData) {
      throw new Error('Failed to load post data')
    }

    // Reset the post object with the loaded content
    const emptyPost = createEmptyPost()
    post = {
      ...emptyPost,
      ...postData,
      // Ensure all required properties are set
      title: postData.title || '',
      description: postData.description || '',
      slug: postData.slug || postId.replace(/\.(md|mdx)$/, ''),
      published: postData.published || new Date().toISOString().split('T')[0],
      content: postData.content || '',
      filepath: postData.filepath || '',
      advanced: {
        ...emptyPost.advanced,
        ...(postData.advanced || {}),
      },
      timelineData: {
        ...emptyPost.timelineData,
        ...(postData.timelineData || {}),
      },
      banner: {
        ...emptyPost.banner,
        ...(postData.banner || {}),
      },
    }

    // Enable advanced options if any of those fields are populated
    if (
      post.advanced.avatarImage ||
      post.advanced.authorName ||
      post.advanced.authorBio ||
      post.advanced.bannerImage ||
      post.advanced.lang !== 'en' ||
      post.advanced.showImageOnPost === true
    ) {
      post.showAdvancedOptions = true
    }

    // Set editing state
    isEditing = true
    selectedPost = postId

    // Switch to the create tab to show the loaded post for editing
    activeTab = 'create'

    showNotification('Post loaded for editing')
  } catch (error: any) {
    console.error('Error loading post:', error)
    showNotification('Failed to load post: ' + error.message, 'error')
  }
}

// Delete a post
async function deletePost(postId: string) {
  if (
    !confirm(
      `Are you sure you want to delete this post? This cannot be undone.`,
    )
  ) {
    return
  }

  try {
    isDeleting = true

    // Find the post
    const postToDelete = localPosts.find(p => p.id === postId)
    if (!postToDelete) {
      throw new Error('Post not found')
    }

    if (isGitHubAuthenticated) {
      // Delete from GitHub repository
      await githubService.deleteFile(
        postToDelete.filepath,
        `Delete post: ${postToDelete.title}`,
      )

      showNotification('Post deleted from GitHub successfully')

      // Remove from localStorage
      const slug = postToDelete.slug || postId.replace(/\.(md|mdx)$/, '')
      localStorage.removeItem(`fullPost_${slug}`)

      // Update cached posts list
      const cachedPostsStr = localStorage.getItem('cachedPosts')
      if (cachedPostsStr) {
        let cachedPosts = JSON.parse(cachedPostsStr)
        cachedPosts = cachedPosts.filter((p: PostMetadata) => p.id !== postId)
        localStorage.setItem('cachedPosts', JSON.stringify(cachedPosts))
      }

      // Refresh the post list
      await fetchLocalPosts()
    } else {
      // Just remove from localStorage
      const slug = postToDelete.slug || postId.replace(/\.(md|mdx)$/, '')
      localStorage.removeItem(`fullPost_${slug}`)

      // Update cached posts list
      const cachedPostsStr = localStorage.getItem('cachedPosts')
      if (cachedPostsStr) {
        let cachedPosts = JSON.parse(cachedPostsStr)
        cachedPosts = cachedPosts.filter((p: PostMetadata) => p.id !== postId)
        localStorage.setItem('cachedPosts', JSON.stringify(cachedPosts))

        // Update the localPosts array
        localPosts = cachedPosts
      }

      showNotification(
        'Post removed from local cache. To delete from GitHub, please authenticate first.',
      )
    }

    // If we were editing this post, reset the form
    if (selectedPost === postId) {
      clearForm()
    }
  } catch (error: any) {
    console.error('Error deleting post:', error)
    showNotification('Failed to delete post: ' + error.message, 'error')
  } finally {
    isDeleting = false
  }
}

// Clear the form
function clearForm() {
  localStorage.removeItem('draftPost')
  post = createEmptyPost()
  isEditing = false
  selectedPost = null
  showNotification('Content cleared!')
}

// Handle import success
function handleImportSuccess(event: CustomEvent<FileImportResult>) {
  const { post: importedPost } = event.detail

  // Update the current post with the imported data
  post = importedPost

  // Switch to create tab to show the imported content
  activeTab = 'create'
  isEditing = false
}

// Handle auto-save
function handleAutosave(event: CustomEvent<{ post: Post }>) {
  const { post: currentPost } = event.detail
  localStorage.setItem('draftPost', JSON.stringify(currentPost))
  console.log('Draft auto-saved')
}

// Handle GitHub integration events
function handleAuthSuccess() {
  if (activeTab === 'browse') fetchLocalPosts()
}

function handleSaveSuccess(
  event: CustomEvent<{ post: Post; isDraft: boolean }>,
) {
  const { post: savedPost, isDraft } = event.detail
  saveCachedPost(savedPost, githubFolder)
  showNotification(
    isDraft
      ? 'Draft saved successfully to GitHub!'
      : 'Post published successfully to GitHub!',
  )
  if (isEditing && activeTab === 'browse') fetchLocalPosts()
  if (!isDraft) isEditing = false
}

function handleSaveError(event: CustomEvent<{ error: string }>) {
  showNotification(`Failed to save to GitHub: ${event.detail.error}`, 'error')
}

function handleRebuildSuccess() {
  showNotification('Site rebuild triggered successfully!', 'success')
}

function handleRebuildError(event: CustomEvent<{ error: string }>) {
  showNotification(`Failed to trigger rebuild: ${event.detail.error}`, 'error')
}

// Handle GitHub save event for window
function handleSaveToGithub(event: CustomEvent) {
  if (event && event.detail) {
    const { post, isDraft } = event.detail
    // Forward event to GithubIntegration component
    const customEvent = new CustomEvent('save-to-github', {
      detail: { post, isDraft },
    })

    // Find and dispatch to GithubIntegration
    const target = document.querySelector(
      'button[data-action="save-to-github"]',
    )
    if (target) target.dispatchEvent(customEvent)
  }
}

// Setup event listeners
onMount(() => {
  const savedDraft = localStorage.getItem('draftPost')
  if (savedDraft) {
    try {
      const savedPost = JSON.parse(savedDraft)
      if (!savedPost.advanced) {
        savedPost.advanced = {
          avatarImage: '',
          authorName: '',
          authorBio: '',
          showImageOnPost: false,
          lang: 'en',
          bannerImage: '',
        }
      }
      post = savedPost
      showNotification('Draft loaded from local storage')
    } catch (e) {
      console.error('Error loading draft:', e)
    }
  }

  // Initialize GitHub service
  initializeGithub()

  // Load cached posts
  cachedPosts = getCachedPosts()

  // Fetch local posts if we're in browse mode
  if (activeTab === 'browse') {
    fetchLocalPosts()
  }

  // Add window event listener
  window.addEventListener('save-to-github', handleSaveToGithub as EventListener)

  return () => {
    window.removeEventListener(
      'save-to-github',
      handleSaveToGithub as EventListener,
    )
  }
})

// Watch for tab changes to load posts when needed
$: if (activeTab === 'browse') {
  fetchLocalPosts()
}
</script>

<div class="post-editor w-full">
  <!-- Toast notification -->
  <ToastNotification 
    message={toastMessage}
    type={toastType}
    show={showToast}
    duration={3000}
  />
  
  <h1 class="text-3xl font-bold text-black/90 dark:text-white/90 mb-6">Post Editor</h1>
  
  <!-- Tab Navigation -->
  <div class="border-b border-neutral-200 dark:border-neutral-700 mb-6">
    <nav class="flex space-x-4">
      <button 
        class="py-2 px-4 font-medium {activeTab === 'create' ? 'text-[var(--primary)] border-b-2 border-[var(--primary)]' : 'text-black/75 dark:text-white/75 hover:text-black/90 dark:hover:text-white/90'}"
        on:click={() => activeTab = 'create'}
      >
        {isEditing ? 'Edit Post' : 'Create New'}
      </button>
      <button 
        class="py-2 px-4 font-medium {activeTab === 'browse' ? 'text-[var(--primary)] border-b-2 border-[var(--primary)]' : 'text-black/75 dark:text-white/75 hover:text-black/90 dark:hover:text-white/90'}"
        on:click={() => activeTab = 'browse'}
      >
        Browse Posts
      </button>
      <button 
        class="py-2 px-4 font-medium {activeTab === 'import' ? 'text-[var(--primary)] border-b-2 border-[var(--primary)]' : 'text-black/75 dark:text-white/75 hover:text-black/90 dark:hover:text-white/90'}"
        on:click={() => activeTab = 'import'}
      >
        Import
      </button>
    </nav>
  </div>
  
  <!-- GitHub Connection Status -->
  <GithubIntegration
    bind:githubService
    bind:isGitHubAuthenticated
    bind:showGitHubAuthForm
    bind:isCommitting
    bind:commitStatus
    bind:showDeployOptions
    bind:githubToken
    bind:githubFolder
    bind:subfolderPath
    on:auth-success={handleAuthSuccess}
    on:save-success={handleSaveSuccess}
    on:save-error={handleSaveError}
    on:rebuild-success={handleRebuildSuccess}
    on:rebuild-error={handleRebuildError}
  />
  
  {#if activeTab === 'browse'}
    <!-- Browse Posts Tab Content -->
    <PostBrowser
      posts={localPosts}
      isLoading={isLoadingPosts}
      loadError={loadError}
      isDeleting={isDeleting}
      selectedPost={selectedPost}
      on:edit={(e) => loadPostForEditing(e.detail.postId)}
      on:delete={(e) => deletePost(e.detail.postId)}
      on:refresh={fetchLocalPosts}
    />
  {:else if activeTab === 'import'}
    <!-- Import Tab Content -->
    <ImportPanel
      on:notification={(e) => showNotification(e.detail.message, e.detail.type)}
      on:import-success={handleImportSuccess}
    />
  {:else}
    <!-- Create/Edit Tab Content -->
    <PostForm
      bind:post
      bind:isEditing
      on:clear={clearForm}
      on:autosave={handleAutosave}
    />
  {/if}
  
  <!-- Action Buttons -->
  <div class="mt-8">
    <!-- Status information -->
    {#if isEditing}
      <div class="p-3 bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800/30 rounded-md text-blue-800 dark:text-blue-200 mb-4">
        <div class="flex items-center">
          <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 mr-2 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          <div>
            <p class="font-medium">Editing Existing Post</p>
            <p class="mt-1 text-sm">You're editing <span class="font-medium">{post.title}</span> from <span class="italic">{post.filepath || 'local storage'}</span>.</p>
          </div>
        </div>
      </div>
    {/if}
  
    <!-- File actions section -->
    <div class="mb-4">
      <h3 class="text-base font-medium text-black/75 dark:text-white/75 mb-2">Local File Actions</h3>
      <div class="flex flex-wrap gap-3">
        <button 
          on:click={clearForm}
          class="px-4 py-2 bg-red-100 dark:bg-red-900 text-red-800 dark:text-red-100 font-medium rounded hover:bg-red-200 dark:hover:bg-red-800 transition"
        >
          {isEditing ? 'Discard Changes' : 'Clear'}
        </button>
        <button 
          on:click={saveDraft}
          class="px-4 py-2 bg-blue-100 dark:bg-blue-900 text-blue-800 dark:text-blue-100 font-medium rounded hover:bg-blue-200 dark:hover:bg-blue-800 transition"
        >
          Save as Local Draft
        </button>
        <button 
          on:click={publishPost}
          disabled={!formValid}
          class="px-4 py-2 bg-blue-600 text-white font-medium rounded hover:bg-blue-700 transition disabled:opacity-50 disabled:cursor-not-allowed"
        >
          Download MDX
        </button>
      </div>
      <p class="mt-2 text-sm text-black/50 dark:text-white/50">
        These actions work without GitHub authentication. The downloaded files must be manually added to your project's content/posts directory.
      </p>
    </div>

    <!-- GitHub actions section -->
    <div>
      <h3 class="text-base font-medium text-black/75 dark:text-white/75 mb-2">GitHub Actions</h3>
      <div class="flex flex-wrap gap-3">
        <button 
          data-action="save-to-github"
          on:click={() => window.dispatchEvent(new CustomEvent('save-to-github', { detail: { post, isDraft: true } }))}
          disabled={!isGitHubAuthenticated || isCommitting || !formValid}
          class="px-4 py-2 bg-blue-100 dark:bg-blue-900 text-blue-800 dark:text-blue-100 font-medium rounded transition-colors flex items-center justify-center disabled:opacity-50"
        >
          {#if isCommitting && !showDeployOptions}
            <svg class="animate-spin -ml-1 mr-2 h-4 w-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
            </svg>
            Saving Draft...
          {:else}
            <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 mr-2" viewBox="0 0 24 24">
              <path fill="currentColor" d="M12 .297c-6.63 0-12 5.373-12 12 0 5.303 3.438 9.8 8.205 11.385.6.113.82-.258.82-.577 0-.285-.01-1.04-.015-2.04-3.338.724-4.042-1.61-4.042-1.61C4.422 18.07 3.633 17.7 3.633 17.7c-1.087-.744.084-.729.084-.729 1.205.084 1.838 1.236 1.838 1.236 1.07 1.835 2.809 1.305 3.495.998.108-.776.417-1.305.76-1.605-2.665-.3-5.466-1.332-5.466-5.93 0-1.31.465-2.38 1.235-3.22-.135-.303-.54-1.523.105-3.176 0 0 1.005-.322 3.3 1.23.96-.267 1.98-.399 3-.405 1.02.006 2.04.138 3 .405 2.28-1.552 3.285-1.23 3.285-1.23.645 1.653.24 2.873.12 3.176.765.84 1.23 1.91 1.23 3.22 0 4.61-2.805 5.625-5.475 5.92.42.36.81 1.096.81 2.22 0 1.606-.015 2.896-.015 3.286 0 .315.21.69.825.57C20.565 22.092 24 17.592 24 12.297c0-6.627-5.373-12-12-12" />
            </svg>
            Save Draft to GitHub
          {/if}
        </button>
        
        <button 
          data-action="save-to-github"
          on:click={() => window.dispatchEvent(new CustomEvent('save-to-github', { detail: { post, isDraft: false } }))}
          disabled={!isGitHubAuthenticated || isCommitting || !formValid}
          class="px-4 py-2 bg-neutral-800 dark:bg-neutral-200 hover:bg-neutral-900 dark:hover:bg-neutral-300 text-white dark:text-neutral-800 font-medium rounded transition-colors flex items-center justify-center disabled:opacity-50"
        >
          {#if isCommitting && !showDeployOptions}
            <svg class="animate-spin -ml-1 mr-2 h-4 w-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
            </svg>
            Publishing Post...
          {:else}
            <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 mr-2" viewBox="0 0 24 24">
              <path fill="currentColor" d="M12 .297c-6.63 0-12 5.373-12 12 0 5.303 3.438 9.8 8.205 11.385.6.113.82-.258.82-.577 0-.285-.01-1.04-.015-2.04-3.338.724-4.042-1.61-4.042-1.61C4.422 18.07 3.633 17.7 3.633 17.7c-1.087-.744.084-.729.084-.729 1.205.084 1.838 1.236 1.838 1.236 1.07 1.835 2.809 1.305 3.495.998.108-.776.417-1.305.76-1.605-2.665-.3-5.466-1.332-5.466-5.93 0-1.31.465-2.38 1.235-3.22-.135-.303-.54-1.523.105-3.176 0 0 1.005-.322 3.3 1.23.96-.267 1.98-.399 3-.405 1.02.006 2.04.138 3 .405 2.28-1.552 3.285-1.23 3.285-1.23.645 1.653.24 2.873.12 3.176.765.84 1.23 1.91 1.23 3.22 0 4.61-2.805 5.625-5.475 5.92.42.36.81 1.096.81 2.22 0 1.606-.015 2.896-.015 3.286 0 .315.21.69.825.57C20.565 22.092 24 17.592 24 12.297c0-6.627-5.373-12-12-12" />
            </svg>
            Publish to GitHub
          {/if}
        </button>
      </div>
      <p class="mt-2 text-sm text-black/50 dark:text-white/50">
        GitHub actions require authentication. Changes are committed directly to your repository and can trigger site rebuilds.
      </p>
    </div>
  </div>
</div>
