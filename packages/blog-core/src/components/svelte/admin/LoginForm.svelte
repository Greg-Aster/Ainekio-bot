<script>
  import { createEventDispatcher, onMount } from 'svelte';
  import { fade, slide } from 'svelte/transition';
  import passwordConfig from '@/config/password.config';
  
  // Event dispatcher for communicating with parent components
  const dispatch = createEventDispatcher();
  
  // Form data
  let username = '';
  let password = '';
  let rememberMe = false;
  
  // UI state
  let isLoading = false;
  let errorMessage = '';
  let formShown = false;
  let isFirstTimeSetup = false;
  const AUTH_KEY = 'isAuthenticated';
  const AUTH_EXP_KEY = 'authExpiresAt';
  const AUTH_TTL_MS = 1000 * 60 * 60 * 8; // 8 hours
  
  // Additional fields for first-time setup
  let confirmPassword = '';

  function setAuthenticated() {
    localStorage.setItem(AUTH_KEY, 'true');
    localStorage.setItem(AUTH_EXP_KEY, String(Date.now() + AUTH_TTL_MS));
  }
  
  // Check setup status on mount
  onMount(() => {
    // If needsSetup is true, don't immediately show setup form
    // Wait for user to click "Get Started"
    isFirstTimeSetup = false;
  });
  
  // Show the login form
  export function show() {
    formShown = true;
  }
  
  // Hide the login form
  export function hide() {
    formShown = false;
  }
  
  // Toggle the form visibility
  export function toggle() {
    formShown = !formShown;
  }
  
  // Start the first-time setup process
  function startFirstTimeSetup() {
    isFirstTimeSetup = true;
  }
  
  // Generate config file content
  function generateConfigFileContent(username, password) {
    // Simple hashing for basic security (not production-grade)
    const hashedPassword = btoa(password); // Base64 encoding for example
    
    return `// Password configuration file
// Generated on ${new Date().toISOString()}
// Replace the existing file in your /config directory

import type { PasswordConfig } from '../types/config';

const passwordConfig: PasswordConfig = {
  username: "${username}",
  passwordHash: "${hashedPassword}",
  needsSetup: false,
  createdAt: "${new Date().toISOString()}"
};

export default passwordConfig;
`;
  }
  
  // Download the generated config file
  function downloadConfigFile(content) {
    const blob = new Blob([content], { type: 'text/typescript' });
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
  }
  
  // Handle first-time setup submission
  function handleSetupSubmit() {
    // Validate inputs
    if (!username || !password) {
      errorMessage = 'Please enter both username and password';
      return;
    }
    
    if (password !== confirmPassword) {
      errorMessage = 'Passwords do not match';
      return;
    }
    
    try {
      // Generate config file content
      const configContent = generateConfigFileContent(username, password);
      
      // Prompt user to download the file
      downloadConfigFile(configContent);
      
      // Show success message
      errorMessage = '';
      
      // Store temporary authentication for this session
      setAuthenticated();
      localStorage.setItem('tempUsername', username);
      
      // Notify parent of successful setup
      dispatch('setup', { username });
      
      // Hide the form
      formShown = false;
      
      // Show alert with instructions
      setTimeout(() => {
        alert('Setup complete! Please replace the existing password.config.ts file in your project\'s /config directory with this new one and redeploy your site.');
      }, 500);
    } catch (error) {
      console.error('Setup error:', error);
      errorMessage = 'An unexpected error occurred during setup. Please try again.';
    }
  }
  
  // Handle regular login form submission
  async function handleSubmit() {
    // Validate inputs
    if (!username || !password) {
      errorMessage = 'Please enter both username and password';
      return;
    }
    
    try {
      isLoading = true;
      errorMessage = '';
      
      // Simulate network delay for better UX
      await new Promise(resolve => setTimeout(resolve, 500));
      
      if (!passwordConfig.needsSetup) {
        // Verify credentials against imported config
        const hashedPassword = btoa(password);
        if (username === passwordConfig.username && hashedPassword === passwordConfig.passwordHash) {
          setAuthenticated();
          dispatch('login', { username });
          formShown = false;
          window.location.reload();
        } else {
          errorMessage = 'Invalid credentials';
        }
      } else {
        // This shouldn't happen normally since we don't show the login form
        // when needsSetup is true, but just in case:
        errorMessage = 'Please complete first-time setup to create your account.';
      }
    } catch (error) {
      console.error('Login error:', error);
      errorMessage = 'An unexpected error occurred. Please try again.';
    } finally {
      isLoading = false;
    }
  }
</script>

{#if formShown}
  <!-- Backdrop -->
  <div 
    class="fixed inset-0 bg-black/25 dark:bg-black/40 z-40" 
    on:click={hide} 
    transition:fade={{ duration: 200 }}
  ></div>
  
  <!-- Login Panel or First-Time Setup -->
  <div 
    class="absolute top-full left-0 mt-1 card-base float-panel p-5 w-72 z-50"
    transition:slide={{ duration: 150, axis: 'y' }}
  >
    {#if passwordConfig.needsSetup && !isFirstTimeSetup}
      <!-- Welcome screen when setup is needed -->
      <div class="space-y-4">
        <h3 class="text-lg font-medium text-center mb-4 text-90">Welcome!</h3>
        <p class="text-sm text-75">It looks like this is your first time logging in. Let's set up your admin credentials.</p>
        <button 
          on:click={startFirstTimeSetup}
          class="w-full py-2 px-4 bg-[var(--primary)] hover:opacity-90 text-white font-medium rounded-md transition-opacity"
        >
          Get Started
        </button>
      </div>
    {:else if passwordConfig.needsSetup && isFirstTimeSetup}
      <!-- First-time setup form -->
      <form on:submit|preventDefault={handleSetupSubmit} class="space-y-4">
        <h3 class="text-lg font-medium text-center mb-4 text-90">Create Admin Account</h3>
        
        {#if errorMessage}
          <div class="bg-red-50 dark:bg-red-900/30 text-red-600 dark:text-red-300 text-sm p-2 rounded border border-red-200 dark:border-red-800">
            {errorMessage}
          </div>
        {/if}
        
        <div>
          <label for="username" class="block text-sm font-medium text-75 mb-1">Choose Username</label>
          <input 
            type="text" 
            id="username" 
            bind:value={username} 
            class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-l text-sm text-neutral-900 dark:text-neutral-100" 
            required 
          />
        </div>
        
        <div>
          <label for="password" class="block text-sm font-medium text-75 mb-1">Choose Password</label>
          <input 
            type="password" 
            id="password" 
            bind:value={password} 
            class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-l text-sm text-neutral-900 dark:text-neutral-100" 
            required 
          />
        </div>
        
        <div>
          <label for="confirm-password" class="block text-sm font-medium text-75 mb-1">Confirm Password</label>
          <input 
            type="password" 
            id="confirm-password" 
            bind:value={confirmPassword} 
            class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-l text-sm text-neutral-900 dark:text-neutral-100" 
            required 
          />
        </div>
        
        <button 
          type="submit" 
          class="w-full py-2 px-4 bg-[var(--primary)] hover:opacity-90 text-white font-medium rounded-md transition-opacity"
        >
          Create Account
        </button>
        
        <p class="text-xs text-75 mt-2">
          After creating your account, you'll need to replace the existing password.config.ts file in your project's /config directory.
        </p>
      </form>
    {:else}
      <!-- Regular login form when setup is already done -->
      <form on:submit|preventDefault={handleSubmit} class="space-y-4">
        <h3 class="text-lg font-medium text-center mb-4 text-90">Admin Login</h3>
        
        {#if errorMessage}
          <div class="bg-red-50 dark:bg-red-900/30 text-red-600 dark:text-red-300 text-sm p-2 rounded border border-red-200 dark:border-red-800">
            {errorMessage}
          </div>
        {/if}
        
        <div>
          <label for="username" class="block text-sm font-medium text-75 mb-1">Username</label>
          <input 
            type="text" 
            id="username" 
            bind:value={username} 
            class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-l text-sm text-neutral-900 dark:text-neutral-100" 
            disabled={isLoading}
            required 
          />
        </div>
        
        <div>
          <label for="password" class="block text-sm font-medium text-75 mb-1">Password</label>
          <input 
            type="password" 
            id="password" 
            bind:value={password} 
            class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-l text-sm text-neutral-900 dark:text-neutral-100" 
            disabled={isLoading}
            required 
          />
        </div>
        
        <div class="flex items-center">
          <input 
            type="checkbox" 
            id="remember-me" 
            bind:checked={rememberMe} 
            class="h-4 w-4 text-[var(--primary)] border-neutral-300 dark:border-neutral-600 rounded" 
            disabled={isLoading}
          />
          <label for="remember-me" class="ml-2 block text-sm text-75">
            Remember me
          </label>
        </div>
        
        <button 
          type="submit" 
          class="w-full py-2 px-4 bg-[var(--primary)] hover:opacity-90 text-white font-medium rounded-md transition-opacity disabled:opacity-60 flex justify-center items-center"
          disabled={isLoading}
        >
          {#if isLoading}
            <svg class="animate-spin -ml-1 mr-2 h-4 w-4 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
            </svg>
            Logging in...
          {:else}
            Login
          {/if}
        </button>
      </form>
    {/if}
  </div>
{/if}
