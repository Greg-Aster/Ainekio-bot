<script lang="ts">
import { createEventDispatcher } from 'svelte'
import { processFileImport } from '../utils/fileUtils'
import type { FileImportResult } from '../utils/fileUtils'

// Initialize event dispatcher
const dispatch = createEventDispatcher<{
  notification: { message: string; type: 'success' | 'error' }
  'import-success': FileImportResult
}>()

// Component state
let fileToImport: File | null = null
let fileType = ''
let importStatus = ''
let isImporting = false

// Handle file selection
function handleFileSelect(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return

  fileToImport = file
  fileType = file.name.split('.').pop()?.toLowerCase() || ''

  importStatus = `Selected file: ${file.name}`
}

// Process import
async function handleImport() {
  if (!fileToImport) {
    dispatch('notification', {
      message: 'Please select a file to import',
      type: 'error',
    })
    return
  }

  importStatus = 'Processing...'
  isImporting = true

  try {
    const importResult = await processFileImport(fileToImport)

    // Notify parent component of successful import
    dispatch('import-success', importResult)

    importStatus =
      'Import successful! You can now edit the content before saving.'
    dispatch('notification', {
      message: 'File imported successfully!',
      type: 'success',
    })
  } catch (error: any) {
    console.error('Import error:', error)
    importStatus = `Error: ${error.message}`

    dispatch('notification', {
      message: `Failed to import file: ${error.message}`,
      type: 'error',
    })
  } finally {
    isImporting = false
  }
}
</script>

<div class="space-y-6">
  <div class="p-6 bg-neutral-50 dark:bg-neutral-800 rounded-lg">
    <h2 class="text-xl font-semibold text-black/80 dark:text-white/80 mb-4">Import Content</h2>
    
    <p class="mb-4 text-neutral-600 dark:text-neutral-300">
      Import content from common file formats and convert to MDX. Supported formats:
    </p>
    
    <ul class="list-disc pl-5 mb-6 text-neutral-600 dark:text-neutral-300">
      <li>Text files (.txt)</li>
      <li>HTML files (.html)</li>
      <li>Markdown files (.md, .markdown)</li>
      <li>MDX files (.mdx) - with full frontmatter parsing</li>
      <li>Word documents (.docx)</li>
    </ul>
    
    <div class="space-y-4">
      <div class="flex flex-col">
        <label for="file-upload" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
          Select a file to import
        </label>
        <input 
          type="file" 
          id="file-upload" 
          accept=".txt,.html,.md,.markdown,.mdx,.docx" 
          on:change={handleFileSelect}
          class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded text-sm text-neutral-900 dark:text-neutral-100" 
        />
      </div>
      
      {#if importStatus}
        <div class="mt-2 p-3 bg-neutral-100 dark:bg-neutral-800 rounded text-sm">
          {importStatus}
        </div>
      {/if}
      
      <div class="flex justify-end mt-4">
        <button 
          on:click={handleImport}
          disabled={!fileToImport || isImporting}
          class="px-4 py-2 bg-blue-600 text-white font-medium rounded hover:bg-blue-700 transition disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {isImporting ? 'Importing...' : 'Import and Convert'}
        </button>
      </div>
    </div>
  </div>
  
  <div class="text-sm text-neutral-500 dark:text-neutral-400">
    <p>After importing, you can edit the content and add metadata before saving or publishing.</p>
  </div>
</div>