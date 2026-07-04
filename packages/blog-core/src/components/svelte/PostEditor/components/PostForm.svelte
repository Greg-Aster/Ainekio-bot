<script lang="ts">
import { marked } from 'marked'
import { createEventDispatcher, onMount } from 'svelte'
import { generateSlugFromTitle } from '../utils/postUtils'
import type { Post } from '../utils/postUtils'

// Initialize event dispatcher
const dispatch = createEventDispatcher<{
  clear: void
  autosave: { post: Post }
}>()

// Props
export let post: Post
export const isEditing = false

// Local state
let editorMode: 'edit' | 'split' | 'preview' = 'edit'
let showMarkdownHelp = false
let isFullscreen = false
let lastSavedAt: Date | null = null
let wordCount = 0
let charCount = 0
let readingTime = 0
const showFormatPanel = false
let searchText = ''
let replaceText = ''
let showSearchReplace = false
let editorElement: HTMLTextAreaElement

// Derived values
$: tagsArray =
  typeof post.tags === 'string'
    ? post.tags
      ? post.tags.split(',').map(tag => tag.trim())
      : []
    : post.tags
$: previewHtml = post.content ? marked(post.content) : ''
$: showVideoFields = post.banner.type === 'video'
$: showTimelineFields = post.timelineData.enabled
$: showAdvancedFields = post.showAdvancedOptions

// Update text statistics whenever content changes
$: {
  if (post.content) {
    // Character count
    charCount = post.content.length

    // Word count
    const words = post.content.match(/\S+/g)
    wordCount = words ? words.length : 0

    // Reading time (average reading speed is around 200-250 words per minute)
    readingTime = Math.max(1, Math.ceil(wordCount / 225))
  } else {
    charCount = 0
    wordCount = 0
    readingTime = 0
  }
}

// Function to insert text at cursor position
function insertTextAtCursor(
  text: string,
  before: string,
  after: string,
  elementId: string,
): string {
  const textarea = document.getElementById(elementId) as HTMLTextAreaElement
  if (!textarea) return text

  const start = textarea.selectionStart
  const end = textarea.selectionEnd
  const selectedText = text.substring(start, end)

  const newText =
    text.substring(0, start) +
    before +
    selectedText +
    after +
    text.substring(end)

  // Set cursor position after insertion
  setTimeout(() => {
    textarea.focus()
    textarea.selectionStart = start + before.length
    textarea.selectionEnd = start + before.length + selectedText.length
  }, 0)

  return newText
}

// Handle keyboard shortcuts
function handleKeydown(event: KeyboardEvent) {
  // Skip if modifiers aren't pressed or if focus is not in editor
  if (!event.ctrlKey && !event.metaKey) return

  // Skip if target is not the editor
  if (!(event.target instanceof HTMLTextAreaElement)) return

  // Format shortcuts
  switch (event.key.toLowerCase()) {
    case 'b': // Bold
      event.preventDefault()
      post.content = insertTextAtCursor(post.content, '**', '**', 'content')
      break
    case 'i': // Italic
      event.preventDefault()
      post.content = insertTextAtCursor(post.content, '_', '_', 'content')
      break
    case 'k': // Link
      event.preventDefault()
      post.content = insertTextAtCursor(post.content, '[', '](url)', 'content')
      break
    case '1': // H1
      if (event.ctrlKey && event.altKey) {
        event.preventDefault()
        post.content = insertTextAtCursor(post.content, '# ', '', 'content')
      }
      break
    case '2': // H2
      if (event.ctrlKey && event.altKey) {
        event.preventDefault()
        post.content = insertTextAtCursor(post.content, '## ', '', 'content')
      }
      break
    case '3': // H3
      if (event.ctrlKey && event.altKey) {
        event.preventDefault()
        post.content = insertTextAtCursor(post.content, '### ', '', 'content')
      }
      break
    case 'l': // List
      if (event.ctrlKey && event.altKey) {
        event.preventDefault()
        post.content = insertTextAtCursor(post.content, '- ', '', 'content')
      }
      break
    case 'f': // Find/Search
      if (!showSearchReplace) {
        event.preventDefault()
        showSearchReplace = true
        setTimeout(() => document.getElementById('search-input')?.focus(), 100)
      }
      break
  }
}

// Auto-format as user types
function handleInput(event: Event) {
  const textarea = event.target as HTMLTextAreaElement
  const value = textarea.value
  const pos = textarea.selectionStart

  // Auto-continue lists
  if (
    event.inputType === 'insertLineBreak' ||
    event.inputType === 'insertParagraph'
  ) {
    const lineStart = value.lastIndexOf('\n', pos - 2) + 1
    const lastLine = value.substring(lineStart, pos - 1) // Get the line before the new one

    // Check for list patterns
    const bulletMatch = lastLine.match(/^(\s*[-*+]\s+)(.*)$/)
    const numberMatch = lastLine.match(/^(\s*\d+\.\s+)(.*)$/)

    if (bulletMatch && !bulletMatch[2].trim()) {
      // Empty bullet point - delete it and the newline
      const newValue = value.substring(0, lineStart) + value.substring(pos)
      post.content = newValue
      setTimeout(() => {
        textarea.selectionStart = lineStart
        textarea.selectionEnd = lineStart
      }, 0)
    } else if (bulletMatch) {
      // Continue bullet list
      const newValue =
        value.substring(0, pos) + bulletMatch[1] + value.substring(pos)
      post.content = newValue
      setTimeout(() => {
        textarea.selectionStart = pos + bulletMatch[1].length
        textarea.selectionEnd = pos + bulletMatch[1].length
      }, 0)
    } else if (numberMatch && !numberMatch[2].trim()) {
      // Empty numbered item - delete it and the newline
      const newValue = value.substring(0, lineStart) + value.substring(pos)
      post.content = newValue
      setTimeout(() => {
        textarea.selectionStart = lineStart
        textarea.selectionEnd = lineStart
      }, 0)
    } else if (numberMatch) {
      // Continue numbered list with incremented number
      const num = Number.parseInt(numberMatch[0]) + 1
      const nextItem = `${num}. `
      const newValue = value.substring(0, pos) + nextItem + value.substring(pos)
      post.content = newValue
      setTimeout(() => {
        textarea.selectionStart = pos + nextItem.length
        textarea.selectionEnd = pos + nextItem.length
      }, 0)
    }
  }
}

// Toggle editor modes
function toggleEditorMode() {
  if (editorMode === 'edit') editorMode = 'split'
  else if (editorMode === 'split') editorMode = 'preview'
  else editorMode = 'edit'
}

// Toggle fullscreen
function toggleFullscreen() {
  isFullscreen = !isFullscreen

  // Focus the editor after switching to fullscreen
  if (isFullscreen) {
    setTimeout(() => {
      editorElement?.focus()
    }, 100)
  }
}

// Search and replace
function handleSearch() {
  if (!searchText) return

  const textarea = document.getElementById('content') as HTMLTextAreaElement
  if (!textarea) return

  const content = textarea.value
  const currentPos = textarea.selectionEnd
  const searchIndex = content.indexOf(searchText, currentPos)

  if (searchIndex !== -1) {
    textarea.focus()
    textarea.setSelectionRange(searchIndex, searchIndex + searchText.length)
  } else {
    // Start from beginning if not found
    const fromStartIndex = content.indexOf(searchText)
    if (fromStartIndex !== -1) {
      textarea.focus()
      textarea.setSelectionRange(
        fromStartIndex,
        fromStartIndex + searchText.length,
      )
    }
  }
}

function handleReplace() {
  if (!searchText) return

  const textarea = document.getElementById('content') as HTMLTextAreaElement
  if (!textarea) return

  const content = textarea.value
  const selStart = textarea.selectionStart
  const selEnd = textarea.selectionEnd

  // Check if current selection matches search text
  if (content.substring(selStart, selEnd) === searchText) {
    post.content =
      content.substring(0, selStart) + replaceText + content.substring(selEnd)
    textarea.focus()
    textarea.setSelectionRange(
      selStart + replaceText.length,
      selStart + replaceText.length,
    )
  }
}

function handleReplaceAll() {
  if (!searchText) return

  post.content = post.content.split(searchText).join(replaceText)
}

// Generate slug from title
function generateSlug() {
  if (post.title) {
    post.slug = generateSlugFromTitle(post.title)
  }
}

// Clear the form
function clearForm() {
  dispatch('clear')
}

// Helper to format date
function formatTime(date: Date): string {
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

// Auto-save draft
onMount(() => {
  // Set editor element reference
  editorElement = document.getElementById('content') as HTMLTextAreaElement

  // Auto-save draft every 30 seconds if there's content
  const autoSaveInterval = setInterval(() => {
    if (post.title) {
      dispatch('autosave', { post })
      lastSavedAt = new Date()
    }
  }, 30000)

  return () => {
    clearInterval(autoSaveInterval)
  }
})
</script>

<div class="grid grid-cols-1 gap-8">
  <!-- Frontmatter Section -->
  <div class="space-y-4">
    <h2 class="text-xl font-semibold text-black/80 dark:text-white/80 mb-3">{isEditing ? 'Edit Post' : 'Post Information'}</h2>
    
    <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
      <div>
        <label for="title" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">Title*</label>
        <input 
          type="text" 
          id="title" 
          bind:value={post.title} 
          on:blur={generateSlug}
          class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded text-sm text-neutral-900 dark:text-neutral-100" 
          required 
        />
      </div>
      
      <div>
        <label for="description" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">Description*</label>
        <input 
          type="text" 
          id="description" 
          bind:value={post.description} 
          class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded text-sm text-neutral-900 dark:text-neutral-100" 
          required 
        />
      </div>
      
      <div>
        <label for="slug" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">Slug*</label>
        <div class="flex">
          <input 
            type="text" 
            id="slug" 
            bind:value={post.slug} 
            class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-l text-sm text-neutral-900 dark:text-neutral-100" 
            required 
          />
          <button 
            on:click={generateSlug} 
            class="px-3 py-2 bg-neutral-200 dark:bg-neutral-600 border border-neutral-300 dark:border-neutral-600 rounded-r text-neutral-700 dark:text-neutral-200"
          >
            <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
              <path fill-rule="evenodd" d="M4 2a1 1 0 011 1v2.101a7.002 7.002 0 0111.601 2.566 1 1 0 11-1.885.666A5.002 5.002 0 005.999 7H9a1 1 0 010 2H4a1 1 0 01-1-1V3a1 1 0 011-1zm.008 9.057a1 1 0 011.276.61A5.002 5.002 0 0014.001 13H11a1 1 0 110-2h5a1 1 0 011 1v5a1 1 0 11-2 0v-2.101a7.002 7.002 0 01-11.601-2.566 1 1 0 01.61-1.276z" clip-rule="evenodd" />
            </svg>
          </button>
        </div>
        <p class="text-xs text-neutral-500 dark:text-neutral-400 mt-1">URL-friendly version of the title (e.g., "my-blog-post")</p>
      </div>
      
      <div>
        <label for="published" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">Publication Date*</label>
        <input 
          type="date" 
          id="published" 
          bind:value={post.published} 
          class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded text-sm text-neutral-900 dark:text-neutral-100" 
          required 
        />
      </div>
      
      <div>
        <label for="image" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">Featured Image URL</label>
        <input 
          type="text" 
          id="image" 
          bind:value={post.image} 
          placeholder="/posts/your-image.jpg" 
          class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded text-sm text-neutral-900 dark:text-neutral-100" 
        />
        {#if post.image}
          <div class="mt-2 p-2 bg-neutral-100 dark:bg-neutral-800 rounded">
            <p class="text-xs mb-1 text-neutral-700 dark:text-neutral-300">Image Preview:</p>
            <img src={post.image} alt="Preview" class="max-h-32 rounded" on:error={(e) => e.target.style.display = 'none'} />
          </div>
        {/if}
      </div>
      
      <div>
        <label for="tags" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">Tags (comma-separated)</label>
        <input 
          type="text" 
          id="tags" 
          bind:value={post.tags} 
          placeholder="news, tutorial, video" 
          class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded text-sm text-neutral-900 dark:text-neutral-100" 
        />
        {#if tagsArray && tagsArray.length > 0}
          <div class="flex flex-wrap gap-1 mt-2">
            {#each tagsArray as tag}
              <span class="px-2 py-1 text-xs bg-neutral-200 dark:bg-neutral-700 rounded text-neutral-800 dark:text-neutral-200">{tag}</span>
            {/each}
          </div>
        {/if}
      </div>
      
      <div>
        <label for="category" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">Category</label>
        <input 
          type="text" 
          id="category" 
          bind:value={post.category} 
          class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded text-sm text-neutral-900 dark:text-neutral-100" 
        />
      </div>
      
      <div class="md:col-span-2">
        <label for="bannerType" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">Banner Type</label>
        <select 
          id="bannerType" 
          bind:value={post.banner.type} 
          class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded text-sm text-neutral-900 dark:text-neutral-100"
        >
          <option value="">None</option>
          <option value="image">Image</option>
          <option value="video">Video</option>
          <option value="timeline">Timeline</option>
        </select>
      </div>
    </div>
    
    {#if showVideoFields}
      <div class="pl-5 space-y-3 border-l-2 border-neutral-200 dark:border-neutral-700">
        <div>
          <label for="videoId" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">YouTube Video ID</label>
          <input 
            type="text" 
            id="videoId" 
            bind:value={post.banner.videoId} 
            placeholder="dQw4w9WgXcQ" 
            class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded text-sm text-neutral-900 dark:text-neutral-100" 
          />
          <p class="text-xs text-neutral-500 dark:text-neutral-400 mt-1">The ID from the YouTube URL (e.g., youtube.com/watch?v=<strong>dQw4w9WgXcQ</strong>)</p>
          
          {#if post.banner.videoId}
            <div class="mt-2 p-2 bg-neutral-100 dark:bg-neutral-800 rounded">
              <p class="text-xs mb-1 text-neutral-700 dark:text-neutral-300">Video Preview:</p>
              <div class="relative pt-[56.25%] bg-black">
                <iframe 
                  src={`https://www.youtube.com/embed/${post.banner.videoId}?autoplay=0&controls=1`}
                  title="YouTube video preview" 
                  class="absolute top-0 left-0 w-full h-full"
                  frameborder="0"
                  allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture;"
                ></iframe>
              </div>
            </div>
          {/if}
        </div>
      </div>
    {/if}
    
    <!-- Timeline specific fields with toggle -->
    <div class="border-t border-neutral-200 dark:border-neutral-700 pt-4">
      <div class="flex items-center mb-2">
        <input 
          type="checkbox" 
          id="enable-timeline" 
          bind:checked={post.timelineData.enabled} 
          class="mr-2" 
        />
        <label for="enable-timeline" class="text-sm font-medium text-neutral-700 dark:text-neutral-300">Add to Timeline</label>
      </div>
      
      {#if showTimelineFields}
        <div class="pl-5 space-y-3 border-l-2 border-neutral-200 dark:border-neutral-700">
          <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label for="timelineYear" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">Timeline Year</label>
              <input 
                type="number" 
                id="timelineYear" 
                bind:value={post.timelineData.year} 
                class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded text-sm text-neutral-900 dark:text-neutral-100" 
              />
            </div>
            
            <div>
              <label for="timelineEra" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">Timeline Era</label>
              <select 
                id="timelineEra" 
                bind:value={post.timelineData.era} 
                class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded text-sm text-neutral-900 dark:text-neutral-100"
              >
                <option value="">Select an era</option>
                <option value="ancient-epoch">The Ancient Epoch</option>
                <option value="awakening-era">The Awakening Era</option>
                <option value="golden-age">The Corporate Golden Age</option>
                <option value="conflict-epoch">Extinction Epoch</option>
                <option value="singularity-conflict">Transtemporal Singularity Conflict</option>
                <option value="transcendent-age">The Transcendent Age</option>
                <option value="final-epoch">The Final Epoch</option>
              </select>
            </div>
            
            <div>
              <label for="timelineLocation" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">Timeline Location</label>
              <input 
                type="text" 
                id="timelineLocation" 
                bind:value={post.timelineData.location} 
                class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded text-sm text-neutral-900 dark:text-neutral-100" 
              />
            </div>
            
            <div class="flex items-center">
              <input 
                type="checkbox" 
                id="isKeyEvent" 
                bind:checked={post.timelineData.isKeyEvent} 
                class="mr-2" 
              />
              <label for="isKeyEvent" class="text-sm font-medium text-neutral-700 dark:text-neutral-300">Key Event</label>
            </div>
          </div>
        </div>
      {/if}
    </div>
    
    <!-- Advanced Options toggle switch -->
    <div class="border-t border-neutral-200 dark:border-neutral-700 pt-4">
      <div class="flex items-center mb-2">
        <input 
          type="checkbox" 
          id="enable-advanced" 
          bind:checked={post.showAdvancedOptions} 
          class="mr-2" 
        />
        <label for="enable-advanced" class="text-sm font-medium text-neutral-700 dark:text-neutral-300">Advanced Options</label>
      </div>
      
      {#if showAdvancedFields}
        <div class="mt-4 space-y-4 border-l-2 border-blue-100 dark:border-blue-900 pl-4">
          <!-- Author section -->
          <div class="space-y-3">
            <h4 class="text-sm font-medium text-neutral-600 dark:text-neutral-400">Custom Author</h4>
            
            <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label for="authorName" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">Author Name</label>
                <input 
                  type="text" 
                  id="authorName" 
                  bind:value={post.advanced.authorName} 
                  class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded text-sm text-neutral-900 dark:text-neutral-100" 
                />
              </div>
              
              <div>
                <label for="authorBio" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">Author Bio</label>
                <input 
                  type="text" 
                  id="authorBio" 
                  bind:value={post.advanced.authorBio} 
                  class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded text-sm text-neutral-900 dark:text-neutral-100" 
                />
              </div>
            </div>
            
            <div>
              <label for="avatarImage" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">Avatar Image URL</label>
              <input 
                type="text" 
                id="avatarImage" 
                bind:value={post.advanced.avatarImage} 
                placeholder="/images/avatar.png" 
                class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded text-sm text-neutral-900 dark:text-neutral-100" 
              />
              {#if post.advanced.avatarImage}
                <div class="mt-2 p-2 bg-neutral-100 dark:bg-neutral-800 rounded">
                  <p class="text-xs mb-1 text-neutral-700 dark:text-neutral-300">Avatar Preview:</p>
                  <img src={post.advanced.avatarImage} alt="Avatar Preview" class="h-12 w-12 rounded-full object-cover" on:error={(e) => e.target.style.display = 'none'} />
                </div>
              {/if}
            </div>
          </div>
          
          <!-- Image and Banner section -->
          <div class="space-y-3">
            <h4 class="text-sm font-medium text-neutral-600 dark:text-neutral-400">Image Settings</h4>
            
            <div class="flex items-center">
              <input 
                type="checkbox" 
                id="showImageOnPost" 
                bind:checked={post.advanced.showImageOnPost} 
                class="mr-2" 
              />
              <label for="showImageOnPost" class="text-sm font-medium text-neutral-700 dark:text-neutral-300">Show Image on Post</label>
            </div>
            
            {#if post.banner.type === 'image'}
              <div>
                <label for="bannerImage" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">Banner Image URL</label>
                <input 
                  type="text" 
                  id="bannerImage" 
                  bind:value={post.advanced.bannerImage} 
                  placeholder="/images/banner.jpg" 
                  class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded text-sm text-neutral-900 dark:text-neutral-100" 
                />
                {#if post.advanced.bannerImage}
                  <div class="mt-2 p-2 bg-neutral-100 dark:bg-neutral-800 rounded">
                    <p class="text-xs mb-1 text-neutral-700 dark:text-neutral-300">Banner Preview:</p>
                    <img src={post.advanced.bannerImage} alt="Banner Preview" class="w-full h-32 object-cover rounded" on:error={(e) => e.target.style.display = 'none'} />
                  </div>
                {/if}
              </div>
            {/if}
          </div>
          
          <!-- Language section -->
          <div>
            <label for="language" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">Language</label>
            <select 
              id="language" 
              bind:value={post.advanced.lang} 
              class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded text-sm text-neutral-900 dark:text-neutral-100"
            >
              <option value="en">English</option>
              <option value="es">Spanish</option>
              <option value="fr">French</option>
              <option value="de">German</option>
              <option value="it">Italian</option>
              <option value="pt">Portuguese</option>
              <option value="ru">Russian</option>
              <option value="zh">Chinese</option>
              <option value="ja">Japanese</option>
              <option value="ko">Korean</option>
            </select>
          </div>
        </div>
      {/if}
    </div>
  </div>
  
  <!-- Content Section -->
  <div class="{isFullscreen ? 'fixed inset-0 bg-white dark:bg-neutral-900 z-50 p-4 overflow-auto' : 'relative'} space-y-4 border-t border-neutral-200 dark:border-neutral-700 pt-6">
    <div class="flex justify-between items-center mb-3">
      <h2 class="text-xl font-semibold text-black/80 dark:text-white/80">Content</h2>
      
      <div class="flex space-x-2">
        <!-- Editor Mode Toggle -->
        <button
          type="button"
          on:click={toggleEditorMode}
          class="px-2 py-1 text-xs font-medium rounded bg-neutral-100 dark:bg-neutral-800 text-neutral-700 dark:text-neutral-300 hover:bg-neutral-200 dark:hover:bg-neutral-700"
        >
          {#if editorMode === 'edit'}
            <span>Split View</span>
          {:else if editorMode === 'split'}
            <span>Preview</span>
          {:else}
            <span>Edit</span>
          {/if}
        </button>
        
        <!-- Fullscreen Toggle -->
        <button
          type="button"
          on:click={toggleFullscreen}
          class="px-2 py-1 text-xs font-medium rounded bg-neutral-100 dark:bg-neutral-800 text-neutral-700 dark:text-neutral-300 hover:bg-neutral-200 dark:hover:bg-neutral-700"
        >
          {#if isFullscreen}
            <span>Exit Fullscreen</span>
          {:else}
            <span>Fullscreen</span>
          {/if}
        </button>
        
        <!-- Markdown Help Toggle -->
        <button
          type="button"
          on:click={() => showMarkdownHelp = !showMarkdownHelp}
          class="px-2 py-1 text-xs font-medium rounded bg-neutral-100 dark:bg-neutral-800 text-neutral-700 dark:text-neutral-300 hover:bg-neutral-200 dark:hover:bg-neutral-700"
        >
          <span>Markdown Help</span>
        </button>
        
        <!-- Search/Replace Toggle -->
        <button
          type="button"
          on:click={() => showSearchReplace = !showSearchReplace}
          class="px-2 py-1 text-xs font-medium rounded bg-neutral-100 dark:bg-neutral-800 text-neutral-700 dark:text-neutral-300 hover:bg-neutral-200 dark:hover:bg-neutral-700"
        >
          <span>Search</span>
        </button>
      </div>
    </div>
    
    <!-- Markdown Cheat Sheet -->
    {#if showMarkdownHelp}
      <div class="p-4 bg-neutral-50 dark:bg-neutral-900 border border-neutral-200 dark:border-neutral-700 rounded-md mb-4">
        <div class="flex justify-between items-start mb-2">
          <h3 class="font-medium text-neutral-900 dark:text-neutral-100">Markdown Cheat Sheet</h3>
          <button 
            type="button" 
            on:click={() => showMarkdownHelp = false}
            class="text-neutral-500 hover:text-neutral-700 dark:text-neutral-400 dark:hover:text-neutral-200"
          >
            <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
              <path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd" />
            </svg>
          </button>
        </div>
        
        <div class="grid grid-cols-1 md:grid-cols-3 gap-4 text-sm">
          <div>
            <h4 class="font-semibold text-neutral-800 dark:text-neutral-200 mb-2">Text Formatting</h4>
            <div class="space-y-1 text-neutral-700 dark:text-neutral-300">
              <div><code class="px-1 bg-neutral-200 dark:bg-neutral-700 rounded"># Heading 1</code></div>
              <div><code class="px-1 bg-neutral-200 dark:bg-neutral-700 rounded">## Heading 2</code></div>
              <div><code class="px-1 bg-neutral-200 dark:bg-neutral-700 rounded">### Heading 3</code></div>
              <div><code class="px-1 bg-neutral-200 dark:bg-neutral-700 rounded">**Bold**</code> or <code class="px-1 bg-neutral-200 dark:bg-neutral-700 rounded">__Bold__</code></div>
              <div><code class="px-1 bg-neutral-200 dark:bg-neutral-700 rounded">*Italic*</code> or <code class="px-1 bg-neutral-200 dark:bg-neutral-700 rounded">_Italic_</code></div>
              <div><code class="px-1 bg-neutral-200 dark:bg-neutral-700 rounded">~~Strikethrough~~</code></div>
            </div>
          </div>
          
          <div>
            <h4 class="font-semibold text-neutral-800 dark:text-neutral-200 mb-2">Lists & Blocks</h4>
            <div class="space-y-1 text-neutral-700 dark:text-neutral-300">
              <div><code class="px-1 bg-neutral-200 dark:bg-neutral-700 rounded">- Item</code> or <code class="px-1 bg-neutral-200 dark:bg-neutral-700 rounded">* Item</code></div>
              <div><code class="px-1 bg-neutral-200 dark:bg-neutral-700 rounded">1. Item</code></div>
              <div><code class="px-1 bg-neutral-200 dark:bg-neutral-700 rounded">> Blockquote</code></div>
              <div><code class="px-1 bg-neutral-200 dark:bg-neutral-700 rounded">```<br>Code Block<br>```</code></div>
              <div><code class="px-1 bg-neutral-200 dark:bg-neutral-700 rounded">`Inline Code`</code></div>
              <div><code class="px-1 bg-neutral-200 dark:bg-neutral-700 rounded">---</code> (Horizontal rule)</div>
            </div>
          </div>
          
          <div>
            <h4 class="font-semibold text-neutral-800 dark:text-neutral-200 mb-2">Links & Media</h4>
            <div class="space-y-1 text-neutral-700 dark:text-neutral-300">
              <div><code class="px-1 bg-neutral-200 dark:bg-neutral-700 rounded">[Link Text](URL)</code></div>
              <div><code class="px-1 bg-neutral-200 dark:bg-neutral-700 rounded">![Alt Text](Image URL)</code></div>
              <div><code class="px-1 bg-neutral-200 dark:bg-neutral-700 rounded">[Link Text][id]<br>[id]: URL "Title"</code></div>
              <div class="mt-2 font-semibold">Keyboard Shortcuts:</div>
              <div><code class="px-1 bg-neutral-200 dark:bg-neutral-700 rounded">Ctrl+B</code> Bold</div>
              <div><code class="px-1 bg-neutral-200 dark:bg-neutral-700 rounded">Ctrl+I</code> Italic</div>
              <div><code class="px-1 bg-neutral-200 dark:bg-neutral-700 rounded">Ctrl+K</code> Link</div>
            </div>
          </div>
        </div>
      </div>
    {/if}
    
    <!-- Search/Replace Panel -->
    {#if showSearchReplace}
      <div class="flex flex-col sm:flex-row gap-2 p-3 bg-neutral-100 dark:bg-neutral-800 border border-neutral-200 dark:border-neutral-700 rounded-md mb-3">
        <div class="flex-1">
          <label for="search-input" class="block text-xs font-medium text-neutral-700 dark:text-neutral-300 mb-1">Search</label>
          <input
            id="search-input"
            type="text"
            bind:value={searchText}
            placeholder="Search text..."
            class="w-full px-2 py-1 text-sm bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded"
          />
        </div>
        
        <div class="flex-1">
          <label for="replace-input" class="block text-xs font-medium text-neutral-700 dark:text-neutral-300 mb-1">Replace</label>
          <input
            id="replace-input"
            type="text"
            bind:value={replaceText}
            placeholder="Replace with..."
            class="w-full px-2 py-1 text-sm bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded"
          />
        </div>
        
        <div class="flex items-end space-x-1">
          <button
            type="button"
            on:click={handleSearch}
            class="px-2 py-1 text-xs bg-blue-100 hover:bg-blue-200 dark:bg-blue-900 dark:hover:bg-blue-800 text-blue-700 dark:text-blue-200 font-medium rounded"
          >
            Find
          </button>
          <button
            type="button"
            on:click={handleReplace}
            class="px-2 py-1 text-xs bg-green-100 hover:bg-green-200 dark:bg-green-900 dark:hover:bg-green-800 text-green-700 dark:text-green-200 font-medium rounded"
          >
            Replace
          </button>
          <button
            type="button"
            on:click={handleReplaceAll}
            class="px-2 py-1 text-xs bg-purple-100 hover:bg-purple-200 dark:bg-purple-900 dark:hover:bg-purple-800 text-purple-700 dark:text-purple-200 font-medium rounded"
          >
            Replace All
          </button>
        </div>
      </div>
    {/if}
    
    <div>
      <label for="content" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">Post Content (Markdown/MDX)</label>
      
      <!-- Editor Area -->
      <div class={editorMode === 'split' ? 'grid grid-cols-1 md:grid-cols-2 gap-4' : ''}>
        <!-- Editor -->
        {#if editorMode !== 'preview'}
          <div class="mb-4">
            <div class="flex flex-wrap gap-1 p-1 bg-neutral-100 dark:bg-neutral-800 border border-neutral-300 dark:border-neutral-600 rounded-t text-neutral-700 dark:text-neutral-300">
              <!-- Formatting buttons -->
              <button type="button" class="p-1 rounded hover:bg-neutral-200 dark:hover:bg-neutral-700" title="Heading 1 (Ctrl+Alt+1)" 
                on:click={() => {
                  post.content = insertTextAtCursor(post.content, '# ', '', 'content');
                }}>
                <span class="font-bold">H1</span>
              </button>
              <button type="button" class="p-1 rounded hover:bg-neutral-200 dark:hover:bg-neutral-700" title="Heading 2 (Ctrl+Alt+2)" 
                on:click={() => {
                  post.content = insertTextAtCursor(post.content, '## ', '', 'content');
                }}>
                <span class="font-bold">H2</span>
              </button>
              <button type="button" class="p-1 rounded hover:bg-neutral-200 dark:hover:bg-neutral-700" title="Heading 3 (Ctrl+Alt+3)" 
                on:click={() => {
                  post.content = insertTextAtCursor(post.content, '### ', '', 'content');
                }}>
                <span class="font-bold">H3</span>
              </button>
              
              <div class="h-6 w-px bg-neutral-300 dark:bg-neutral-600 mx-1"></div>
              
              <button type="button" class="p-1 rounded hover:bg-neutral-200 dark:hover:bg-neutral-700" title="Bold (Ctrl+B)" 
                on:click={() => {
                  post.content = insertTextAtCursor(post.content, '**', '**', 'content');
                }}>
                <span class="font-bold">B</span>
              </button>
              <button type="button" class="p-1 rounded hover:bg-neutral-200 dark:hover:bg-neutral-700" title="Italic (Ctrl+I)" 
                on:click={() => {
                  post.content = insertTextAtCursor(post.content, '_', '_', 'content');
                }}>
                <span class="italic">I</span>
              </button>
              <button type="button" class="p-1 rounded hover:bg-neutral-200 dark:hover:bg-neutral-700" title="Strikethrough" 
                on:click={() => {
                  post.content = insertTextAtCursor(post.content, '~~', '~~', 'content');
                }}>
                <span class="line-through">S</span>
              </button>
              
              <div class="h-6 w-px bg-neutral-300 dark:bg-neutral-600 mx-1"></div>
              
              <button type="button" class="p-1 rounded hover:bg-neutral-200 dark:hover:bg-neutral-700" title="Bullet List (Ctrl+Alt+L)" 
                on:click={() => {
                  post.content = insertTextAtCursor(post.content, '- ', '', 'content');
                }}>
                <span>• List</span>
              </button>
              <button type="button" class="p-1 rounded hover:bg-neutral-200 dark:hover:bg-neutral-700" title="Numbered List" 
                on:click={() => {
                  post.content = insertTextAtCursor(post.content, '1. ', '', 'content');
                }}>
                <span>1. List</span>
              </button>
              <button type="button" class="p-1 rounded hover:bg-neutral-200 dark:hover:bg-neutral-700" title="Task List" 
                on:click={() => {
                  post.content = insertTextAtCursor(post.content, '- [ ] ', '', 'content');
                }}>
                <span>☐ Task</span>
              </button>
              
              <div class="h-6 w-px bg-neutral-300 dark:bg-neutral-600 mx-1"></div>
              
              <button type="button" class="p-1 rounded hover:bg-neutral-200 dark:hover:bg-neutral-700" title="Link (Ctrl+K)" 
                on:click={() => {
                  post.content = insertTextAtCursor(post.content, '[', '](url)', 'content');
                }}>
                <span>🔗 Link</span>
              </button>
              <button type="button" class="p-1 rounded hover:bg-neutral-200 dark:hover:bg-neutral-700" title="Image" 
                on:click={() => {
                  post.content = insertTextAtCursor(post.content, '![alt text](', ')', 'content');
                }}>
                <span>🖼️ Image</span>
              </button>
              
              <div class="h-6 w-px bg-neutral-300 dark:bg-neutral-600 mx-1"></div>
              
              <button type="button" class="p-1 rounded hover:bg-neutral-200 dark:hover:bg-neutral-700" title="Code Block" 
                on:click={() => {
                  post.content = insertTextAtCursor(post.content, '```\n', '\n```', 'content');
                }}>
                <span>Code</span>
              </button>
              <button type="button" class="p-1 rounded hover:bg-neutral-200 dark:hover:bg-neutral-700" title="Inline Code" 
                on:click={() => {
                  post.content = insertTextAtCursor(post.content, '`', '`', 'content');
                }}>
                <span>{'`'}</span>
              </button>
              <button type="button" class="p-1 rounded hover:bg-neutral-200 dark:hover:bg-neutral-700" title="Table" 
                on:click={() => {
                  post.content = insertTextAtCursor(post.content, '| Header | Header |\n| ------ | ------ |\n| Cell   | Cell   |\n', '', 'content');
                }}>
                <span>Table</span>
              </button>
              <button type="button" class="p-1 rounded hover:bg-neutral-200 dark:hover:bg-neutral-700" title="Quote" 
                on:click={() => {
                  post.content = insertTextAtCursor(post.content, '> ', '', 'content');
                }}>
                <span>Quote</span>
              </button>
              
              <div class="h-6 w-px bg-neutral-300 dark:bg-neutral-600 mx-1"></div>
              
              <button type="button" class="p-1 rounded hover:bg-neutral-200 dark:hover:bg-neutral-700" title="Horizontal Rule" 
                on:click={() => {
                  post.content = insertTextAtCursor(post.content, '\n---\n', '', 'content');
                }}>
                <span>―</span>
              </button>
              
              <div class="flex-grow"></div>
              
              <div class="text-xs text-neutral-500 dark:text-neutral-400 flex items-center gap-2">
                <span>{wordCount} words</span>
                <span>~{readingTime} min read</span>
                {#if lastSavedAt}
                  <span>Saved at {formatTime(lastSavedAt)}</span>
                {/if}
              </div>
            </div>
            <textarea 
              id="content" 
              bind:value={post.content} 
              bind:this={editorElement}
              on:keydown={handleKeydown}
              on:input={handleInput}
              rows="20" 
              class="w-full px-3 py-2 bg-white dark:bg-neutral-800 border border-neutral-300 dark:border-neutral-600 border-t-0 rounded-b text-sm font-mono text-neutral-900 dark:text-white"
            ></textarea>
          </div>
        {/if}
        
        <!-- Preview -->
        {#if editorMode === 'preview' || editorMode === 'split'}
          <div class="p-4 bg-white dark:bg-neutral-800 rounded min-h-[400px] max-h-[800px] overflow-auto custom-md border border-neutral-200 dark:border-neutral-700">
            {@html previewHtml || '<p class="text-neutral-400 dark:text-neutral-500">Nothing to preview yet...</p>'}
          </div>
        {/if}
      </div>
    </div>
  </div>
</div>