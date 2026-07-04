<script lang="ts">
import { createEventDispatcher } from 'svelte'
import { formatDate } from '../utils/postUtils'
import type { PostMetadata } from '../utils/postUtils'

// Initialize event dispatcher
const dispatch = createEventDispatcher<{
  edit: { postId: string }
  delete: { postId: string }
  refresh: void
}>()

// Props
export const posts: PostMetadata[] = []
export const isLoading = false
export const loadError: string | null = null
export const isDeleting = false
export const selectedPost: string | null = null

// Local state
let searchQuery = ''

// Reactive filtered posts
$: filteredPosts = searchQuery
  ? posts.filter(
      p =>
        p.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
        p.description.toLowerCase().includes(searchQuery.toLowerCase()) ||
        (p.tags &&
          Array.isArray(p.tags) &&
          p.tags.some(tag =>
            tag.toLowerCase().includes(searchQuery.toLowerCase()),
          )),
    )
  : posts

// Functions
function handleEditClick(postId: string) {
  dispatch('edit', { postId })
}

function handleDeleteClick(postId: string) {
  dispatch('delete', { postId })
}

function handleRefreshClick() {
  dispatch('refresh')
}
</script>

<div class="p-6 bg-neutral-50 dark:bg-neutral-800 rounded-lg">
  <h2 class="text-xl font-semibold text-black/80 dark:text-white/80 mb-4">Browse Posts</h2>
  
  {#if isLoading}
    <div class="flex justify-center py-8">
      <div class="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-500"></div>
    </div>
  {:else if loadError}
    <div class="bg-red-50 dark:bg-red-900/30 text-red-600 dark:text-red-300 text-sm p-4 rounded border border-red-200 dark:border-red-800 mb-4">
      {loadError}
    </div>
  {:else}
    <!-- Search and filter -->
    <div class="mb-6">
      <div class="relative">
        <input 
          type="text" 
          bind:value={searchQuery} 
          placeholder="Search by title, description, or tag..." 
          class="w-full px-4 py-2 pl-10 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded text-sm"
        />
        <div class="absolute inset-y-0 left-0 flex items-center pl-3 pointer-events-none">
          <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 text-neutral-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
        </div>
      </div>
    </div>
    
    <!-- Post List -->
    {#if filteredPosts.length === 0}
      <div class="text-center py-8 text-neutral-500 dark:text-neutral-400">
        {searchQuery ? 'No posts match your search criteria.' : 'No posts found. Connect to GitHub or add posts locally.'}
      </div>
    {:else}
      <div class="space-y-4">
        {#each filteredPosts as post (post.id)}
          <div class="bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-lg overflow-hidden shadow-sm hover:shadow-md transition-shadow post-card">
            <div class="p-4">
              <div class="flex justify-between items-start">
                <div>
                  <h3 class="text-lg font-medium text-black/80 dark:text-white/80 mb-1">
                    {post.title}
                    {#if post.draft}
                      <span class="ml-2 px-2 py-0.5 text-xs bg-amber-100 dark:bg-amber-900 text-amber-800 dark:text-amber-200 rounded">
                        Draft
                      </span>
                    {/if}
                    {#if post.error}
                      <span class="ml-2 px-2 py-0.5 text-xs bg-red-100 dark:bg-red-900 text-red-800 dark:text-red-200 rounded">
                        Error
                      </span>
                    {/if}
                  </h3>
                  <p class="text-sm text-neutral-600 dark:text-neutral-300 mb-2">{post.description}</p>
                  
                  <div class="flex flex-wrap items-center text-xs text-neutral-500 dark:text-neutral-400 gap-4 mb-4">
                    <div class="flex items-center">
                      <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 mr-1" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
                      </svg>
                      {formatDate(post.published)}
                    </div>
                    
                    {#if post.updated && post.updated !== post.published}
                      <div class="flex items-center">
                        <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 mr-1" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                        </svg>
                        Updated: {formatDate(post.updated)}
                      </div>
                    {/if}
                    
                    {#if post.category}
                      <div class="flex items-center">
                        <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 mr-1" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 7h.01M7 3h5c.512 0 1.024.195 1.414.586l7 7a2 2 0 010 2.828l-7 7a2 2 0 01-2.828 0l-7-7A1.994 1.994 0 013 12V7a4 4 0 014-4z" />
                        </svg>
                        {post.category}
                      </div>
                    {/if}
                  </div>
                  
                  {#if post.tags && post.tags.length > 0}
                    <div class="flex flex-wrap gap-1 mt-1 mb-2">
                      {#each post.tags as tag}
                        <span class="px-2 py-1 text-xs bg-neutral-200 dark:bg-neutral-600 rounded">{tag}</span>
                      {/each}
                    </div>
                  {/if}
                </div>
                
                <!-- Actions -->
                <div class="flex space-x-2">
                  <button 
                    on:click={() => handleEditClick(post.id)}
                    class="p-2 text-blue-600 dark:text-blue-400 hover:bg-blue-50 dark:hover:bg-blue-900/20 rounded-full"
                    title="Edit Post"
                  >
                    <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                    </svg>
                  </button>
                  
                  <button 
                    on:click={() => handleDeleteClick(post.id)}
                    disabled={isDeleting}
                    class="p-2 text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 rounded-full"
                    title="Delete Post"
                  >
                    {#if isDeleting && selectedPost === post.id}
                      <svg class="animate-spin h-5 w-5" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                      </svg>
                    {:else}
                      <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                      </svg>
                    {/if}
                  </button>
                </div>
              </div>
            </div>
          </div>
        {/each}
      </div>
    {/if}
  {/if}
  
  <!-- Refresh button -->
  <div class="flex justify-center mt-6">
    <button 
      on:click={handleRefreshClick}
      disabled={isLoading}
      class="px-4 py-2 bg-blue-100 dark:bg-blue-900 text-blue-800 dark:text-blue-100 font-medium rounded hover:bg-blue-200 dark:hover:bg-blue-800 transition disabled:opacity-50"
    >
      {#if isLoading}
        <svg class="animate-spin -ml-1 mr-2 h-4 w-4 inline-block" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
        </svg>
        Loading...
      {:else}
        <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 inline-block mr-1" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
        </svg>
        Refresh Posts
      {/if}
    </button>
  </div>
</div>

<style>
  /* Post card hover animation */
  :global(.post-card) {
    @apply transition-all duration-200 ease-in-out;
  }
  
  :global(.post-card:hover) {
    @apply transform -translate-y-0.5 shadow-md;
  }
</style>