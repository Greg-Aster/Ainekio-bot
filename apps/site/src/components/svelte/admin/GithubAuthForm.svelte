<script>
  import { createEventDispatcher } from 'svelte';

  // Props
  export let isAuthenticating = false;
  export let errorMessage = '';
  export let token = '';

  // Create event dispatcher
  const dispatch = createEventDispatcher();

  // Handle auth submission
  function handleSubmit() {
    if (!token.trim()) {
      dispatch('error', 'Please enter a valid token');
      return;
    }
    dispatch('authenticate', token);
  }

  // Handle cancel
  function handleCancel() {
    dispatch('cancel');
  }
</script>

<div class="auth-form bg-neutral-50 dark:bg-neutral-800/50 p-5 rounded-lg border border-neutral-300 dark:border-neutral-600 mb-4">
  <h4 class="text-base font-medium mb-4">GitHub Authentication</h4>
  
  <div class="mb-6">
    <p class="text-neutral-600 dark:text-neutral-400 mb-4">
      To publish directly to your GitHub repository, you'll need to create a Personal Access Token (PAT) with repository access.
    </p>
    
    <div class="bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800/30 p-3 rounded-md text-sm mb-4">
      <h5 class="font-medium text-blue-800 dark:text-blue-200 mb-1">How to create a GitHub Personal Access Token:</h5>
      <ol class="list-decimal pl-5 text-blue-700 dark:text-blue-300 space-y-1">
        <li>Go to <a href="https://github.com/settings/tokens" target="_blank" class="underline">GitHub Settings &gt; Developer settings &gt; Personal access tokens</a></li>
        <li>Click "Generate new token" (classic)</li>
        <li>Add a note (e.g., "Blog Admin")</li>
        <li>Set expiration as needed</li>
        <li>Select "repo" scope permissions</li>
        <li>Click "Generate token"</li>
        <li>Copy the token immediately (you won't see it again)</li>
      </ol>
    </div>
  </div>
  
  {#if errorMessage}
    <div class="bg-red-50 dark:bg-red-900/30 text-red-600 dark:text-red-300 text-sm p-3 rounded border border-red-200 dark:border-red-800 mb-4">
      {errorMessage}
    </div>
  {/if}
  
  <div class="space-y-4">
    <div class="form-group">
      <label for="github-token" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
        Personal Access Token
      </label>
      <input 
        type="password" 
        id="github-token" 
        bind:value={token} 
        placeholder="ghp_xxxxxxxxxxxxxxxxxxxx" 
        class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm" 
        disabled={isAuthenticating}
      />
      <p class="mt-1 text-xs text-neutral-500 dark:text-neutral-400">
        Your token is stored locally and only used for GitHub API requests.
      </p>
    </div>
    
    <div class="flex justify-end space-x-3">
      <button 
        on:click={handleCancel}
        class="px-4 py-2 border border-neutral-300 dark:border-neutral-600 text-neutral-700 dark:text-neutral-300 rounded-md hover:bg-neutral-50 dark:hover:bg-neutral-700 transition-colors"
      >
        Cancel
      </button>
      
      <button 
        on:click={handleSubmit}
        disabled={isAuthenticating || !token}
        class="px-4 py-2 bg-[var(--primary)] hover:opacity-90 text-white font-medium rounded-md transition-opacity flex items-center disabled:opacity-50"
      >
        {#if isAuthenticating}
          <svg class="animate-spin -ml-1 mr-2 h-4 w-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
          </svg>
          Authenticating...
        {:else}
          Authenticate
        {/if}
      </button>
    </div>
  </div>
</div>