<script>
    import { createEventDispatcher } from 'svelte';
    import { fade } from 'svelte/transition';
    
    // Event dispatcher for notifying parent components
    const dispatch = createEventDispatcher();
    
    // State variables
    let showConfirmDialog = false;
    let resetInProgress = false;
    let resetComplete = false;
    
    // Function to show confirmation dialog
    function promptPasswordReset() {
      showConfirmDialog = true;
    }
    
    // Function to cancel the password reset
    function cancelPasswordReset() {
      showConfirmDialog = false;
    }
    
    // Function to generate a reset password config file
    function resetPassword() {
      resetInProgress = true;
      
      try {
        // Generate default password config file with needsSetup = true
        const resetConfigContent = `// Password configuration file
  // Reset on ${new Date().toISOString()}
  // Place this file in your /config directory to trigger password setup
  
  import type { PasswordConfig } from './config';
  
  const passwordConfig: PasswordConfig = {
    username: '',
    passwordHash: '',
    needsSetup: true,
    createdAt: ''
  };
  
  export default passwordConfig;
  `;
        
        // Create and download the file
        const blob = new Blob([resetConfigContent], { type: 'text/typescript' });
        const url = URL.createObjectURL(blob);
        
        const a = document.createElement('a');
        a.href = url;
        a.download = 'password.config.ts';
        document.body.appendChild(a);
        a.click();
        
        // Cleanup
        setTimeout(() => {
          document.body.removeChild(a);
          URL.revokeObjectURL(url);
        }, 0);
        
        // Mark as complete
        resetComplete = true;
        showConfirmDialog = false;
        
        // Notify of changes
        dispatch('change');
        
        // Reset UI after a delay
        setTimeout(() => {
          resetComplete = false;
          resetInProgress = false;
        }, 3000);
      } catch (error) {
        console.error('Error generating password reset file:', error);
        resetInProgress = false;
      }
    }
  </script>
  
  <div class="security-config-tab space-y-8">
    <div>
      <h2 class="text-xl font-semibold text-black/90 dark:text-white/90 mb-4">Security Settings</h2>
      <p class="text-neutral-600 dark:text-neutral-400 mb-6">
        Manage security settings for your website.
      </p>
    </div>
    
  <!-- Password Management Section -->
  <div class="card-base p-6 rounded-lg shadow-sm">
    <h3 class="text-lg font-medium text-black/80 dark:text-white/80 mb-4">Password Management</h3>
    
    <div class="border-t border-neutral-200 dark:border-neutral-700 pt-4 mt-4">
      <div class="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h4 class="text-md font-medium text-neutral-800 dark:text-neutral-200">Reset Admin Password</h4>
          <p class="text-sm text-neutral-600 dark:text-neutral-400 mt-1">
            Reset your admin password by generating a new configuration file. This will trigger the password setup process on your next login.
          </p>
        </div>
          
          <button 
            on:click={promptPasswordReset}
            disabled={resetInProgress || resetComplete}
            class="py-2 px-4 bg-red-600 hover:bg-red-700 text-white font-medium rounded-md transition-colors flex items-center disabled:opacity-60 whitespace-nowrap"
          >
            {#if resetInProgress}
              <svg class="animate-spin -ml-1 mr-2 h-4 w-4 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
              </svg>
              Resetting...
            {:else if resetComplete}
              <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 mr-2" viewBox="0 0 20 20" fill="currentColor">
                <path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd" />
              </svg>
              Reset Complete
            {:else}
              <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 mr-2" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4"></path>
              </svg>
              Reset Password
            {/if}
          </button>
        </div>
      </div>
    </div>
    
    <!-- Additional security sections could be added here in the future -->
  </div>
  
  <!-- Confirmation Dialog -->
  {#if showConfirmDialog}
    <div transition:fade={{ duration: 200 }} class="fixed inset-0 bg-black/25 dark:bg-black/40 z-50 flex items-center justify-center">
      <div class="card-base p-6 rounded-lg shadow-lg max-w-md mx-auto">
        <h3 class="text-lg font-bold mb-2">Confirm Password Reset</h3>
        <p class="text-neutral-600 dark:text-neutral-400 mb-4">
          Are you sure you want to reset your admin password? This will generate a new configuration file that you'll need to add to your project.
        </p>
        <p class="text-sm text-amber-600 dark:text-amber-400 mb-6">
          You will need to complete the password setup process on your next login.
        </p>
        
        <div class="flex justify-end space-x-3">
          <button 
            on:click={cancelPasswordReset}
            class="py-2 px-4 bg-neutral-200 dark:bg-neutral-700 hover:bg-neutral-300 dark:hover:bg-neutral-600 text-neutral-800 dark:text-neutral-200 font-medium rounded-md transition-colors"
          >
            Cancel
          </button>
          <button 
            on:click={resetPassword}
            class="py-2 px-4 bg-red-600 hover:bg-red-700 text-white font-medium rounded-md transition-colors"
          >
            Reset Password
          </button>
        </div>
      </div>
    </div>
  {/if}
  
  <style>
    /* Add any component-specific styles here */
  </style>