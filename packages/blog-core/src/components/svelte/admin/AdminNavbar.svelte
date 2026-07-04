<script>
  import { onMount } from 'svelte';
  import { slide } from 'svelte/transition';
  import LoginForm from './LoginForm.svelte';

  // Props
  export let siteTitle = 'Blog';
  
  // State
  let isAuthenticatedState = false;
  let showAdminDropdown = false;
  let loginFormRef;
  const AUTH_KEY = 'isAuthenticated';
  const AUTH_EXP_KEY = 'authExpiresAt';
  
  // Check authentication status on mount
  onMount(() => {
    isAuthenticatedState = hasValidAuth();
  });

  function clearAuth() {
    localStorage.removeItem(AUTH_KEY);
    localStorage.removeItem(AUTH_EXP_KEY);
  }

  function hasValidAuth() {
    const isAuthenticated = localStorage.getItem(AUTH_KEY) === 'true';
    const expiresAt = Number(localStorage.getItem(AUTH_EXP_KEY) || '0');
    if (!isAuthenticated || !expiresAt || Date.now() >= expiresAt) {
      clearAuth();
      return false;
    }
    return true;
  }
  
  // Handle button click
  function handleButtonClick(event) {
    if (!isAuthenticatedState) {
      // When not logged in, show login form
      event.preventDefault();
      loginFormRef.toggle();
    } else {
      // When logged in, toggle dropdown
      event.preventDefault();
      toggleAdminDropdown();
    }
  }
  
  // Handle successful login
  function handleLogin() {
    isAuthenticatedState = true;
  }
  
  // Handle successful setup
  function handleSetup() {
    isAuthenticatedState = true;
  }
  
  // Handle logout
  function handleLogout() {
    clearAuth();
    isAuthenticatedState = false;
    window.location.href = '/';
  }
  
  // Toggle admin dropdown
  function toggleAdminDropdown() {
    showAdminDropdown = !showAdminDropdown;
  }
  
  // Close dropdown when clicking outside
  function handleClickOutside(event) {
    if (showAdminDropdown && !event.target.closest('.admin-dropdown')) {
      showAdminDropdown = false;
    }
  }
</script>

<svelte:window on:click={handleClickOutside} />

<div class="admin-navbar-component">
  <!-- Home Button / Settings Button -->
  <div class="admin-dropdown relative">
    <a 
      href={isAuthenticatedState ? "#" : "/"} 
      on:click={handleButtonClick}
      class="btn-plain scale-animation rounded-lg h-[3.25rem] px-5 font-bold active:scale-95 flex items-center"
    >
      <div class="flex flex-row items-center text-md">
        {#if isAuthenticatedState}
          <!-- Settings Icon (when logged in) -->
          <svg xmlns="http://www.w3.org/2000/svg" class="text-[1.75rem] mb-1 mr-2" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="3"></circle>
            <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"></path>
          </svg>
        {:else}
          <!-- Home Icon (when not logged in) -->
          <svg xmlns="http://www.w3.org/2000/svg" class="text-[1.75rem] mb-1 mr-2" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"></path>
            <polyline points="9 22 9 12 15 12 15 22"></polyline>
          </svg>
        {/if}
        {siteTitle}
      </div>
    </a>
    
 <!-- Dropdown Menu (only when authenticated) -->
 {#if isAuthenticatedState && showAdminDropdown}
 <div 
   class="absolute left-0 mt-1 w-48 rounded-lg shadow-lg card-base float-panel py-1 z-50"
   transition:slide={{ duration: 150, axis: 'y' }}
 >
   <a href="/new-post/" class="block px-4 py-2 text-75 hover:bg-[var(--btn-plain-bg-hover)] hover:text-[var(--primary)] transition-colors duration-200">
     <div class="flex items-center">
       <svg xmlns="http://www.w3.org/2000/svg" class="text-[1.25rem] mr-2" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
         <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path>
         <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path>
       </svg>
       New Post
     </div>
   </a>
   <a href="/configs/" class="block px-4 py-2 text-75 hover:bg-[var(--btn-plain-bg-hover)] hover:text-[var(--primary)] transition-colors duration-200">
     <div class="flex items-center">
       <svg xmlns="http://www.w3.org/2000/svg" class="text-[1.25rem] mr-2" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
         <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
         <polyline points="14 2 14 8 20 8"></polyline>
         <line x1="16" y1="13" x2="8" y2="13"></line>
         <line x1="16" y1="17" x2="8" y2="17"></line>
         <polyline points="10 9 9 9 8 9"></polyline>
       </svg>
       Configs
     </div>
   </a>
   <a href="/friends/" class="block px-4 py-2 text-75 hover:bg-[var(--btn-plain-bg-hover)] hover:text-[var(--primary)] transition-colors duration-200">
     <div class="flex items-center">
       <svg xmlns="http://www.w3.org/2000/svg" class="text-[1.25rem] mr-2" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
         <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"></path>
         <circle cx="9" cy="7" r="4"></circle>
         <path d="M23 21v-2a4 4 0 0 0-3-3.87"></path>
         <path d="M16 3.13a4 4 0 0 1 0 7.75"></path>
       </svg>
       Friends
     </div>
   </a>
   <a href="/" class="block px-4 py-2 text-75 hover:bg-[var(--btn-plain-bg-hover)] hover:text-[var(--primary)] transition-colors duration-200">
     <div class="flex items-center">
       <svg xmlns="http://www.w3.org/2000/svg" class="text-[1.25rem] mr-2" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
         <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"></path>
         <polyline points="9 22 9 12 15 12 15 22"></polyline>
       </svg>
       Home
     </div>
   </a>
   <div class="border-t border-neutral-200 dark:border-neutral-700 my-1"></div>
   <button 
     on:click={handleLogout}
     class="block w-full text-left px-4 py-2 text-75 hover:bg-[var(--btn-plain-bg-hover)] hover:text-red-500 transition-colors duration-200"
   >
     <div class="flex items-center">
       <svg xmlns="http://www.w3.org/2000/svg" class="text-[1.25rem] mr-2" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
         <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"></path>
         <polyline points="16 17 21 12 16 7"></polyline>
         <line x1="21" y1="12" x2="9" y2="12"></line>
       </svg>
       Logout
     </div>
   </button>
 </div>
{/if}
</div>

<!-- Login Form Component -->
<LoginForm bind:this={loginFormRef} on:login={handleLogin} on:setup={handleSetup} />
</div>

<style>
.admin-navbar-component {
display: flex;
align-items: center;
}
</style>
