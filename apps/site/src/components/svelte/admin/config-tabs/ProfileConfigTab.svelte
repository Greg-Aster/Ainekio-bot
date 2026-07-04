<script>
  import { createEventDispatcher, onMount } from 'svelte';
  
  // Props
  export let profileConfig;
  export let avatarConfig;
  
  // Local state
  let editingSocial = null;
  let showSocialEditor = false;
  let isAvatarSequence = false;
  let avatarCount = 0;
  let selectedAvatarIndex = 0;
  
  // Event dispatcher
  const dispatch = createEventDispatcher();
  
  // Common social media platforms with icons
  const socialPlatforms = [
    { name: 'Twitter', icon: 'fa6-brands:twitter', prefix: 'https://twitter.com/' },
    { name: 'GitHub', icon: 'fa6-brands:github', prefix: 'https://github.com/' },
    { name: 'LinkedIn', icon: 'fa6-brands:linkedin', prefix: 'https://linkedin.com/in/' },
    { name: 'Instagram', icon: 'fa6-brands:instagram', prefix: 'https://instagram.com/' },
    { name: 'YouTube', icon: 'fa6-brands:youtube', prefix: 'https://youtube.com/' },
    { name: 'Facebook', icon: 'fa6-brands:facebook', prefix: 'https://facebook.com/' },
    { name: 'Discord', icon: 'fa6-brands:discord', prefix: '' },
    { name: 'Twitch', icon: 'fa6-brands:twitch', prefix: 'https://twitch.tv/' },
    { name: 'Reddit', icon: 'fa6-brands:reddit', prefix: 'https://reddit.com/user/' },
    { name: 'Medium', icon: 'fa6-brands:medium', prefix: 'https://medium.com/@' },
    { name: 'Dev.to', icon: 'fa6-brands:dev', prefix: 'https://dev.to/' },
    { name: 'Patreon', icon: 'fa6-brands:patreon', prefix: 'https://patreon.com/' },
    { name: 'Ko-fi', icon: 'fa6-brands:kofi', prefix: 'https://ko-fi.com/' },
    { name: 'Bluesky', icon: 'fa6-brands:bluesky', prefix: 'https://bsky.app/profile/' },
    { name: 'Mastodon', icon: 'fa6-brands:mastodon', prefix: '' },
    { name: 'Email', icon: 'fa6-solid:envelope', prefix: 'mailto:' },
    { name: 'Website', icon: 'fa6-solid:globe', prefix: 'https://' },
    { name: 'Custom', icon: 'fa6-solid:link', prefix: '' }
  ];
  
  // Function to add a social link
  function addSocialLink() {
    editingSocial = {
      isNew: true,
      data: {
        name: '',
        icon: '',
        url: ''
      },
      platformIndex: null
    };
    showSocialEditor = true;
  }
  
  // Function to edit a social link
  function editSocialLink(index) {
    editingSocial = {
      isNew: false,
      index: index,
      data: { ...profileConfig.links[index] },
      platformIndex: null
    };
    
    // Try to find the platform index
    const platform = socialPlatforms.findIndex(p => p.icon === profileConfig.links[index].icon);
    if (platform !== -1) {
      editingSocial.platformIndex = platform;
    }
    
    showSocialEditor = true;
  }
  
  // Function to save social link
  function saveSocialLink() {
    // Update icon if platform selected
    if (editingSocial.platformIndex !== null) {
      editingSocial.data.icon = socialPlatforms[editingSocial.platformIndex].icon;
      
      // If it's a new link and name is empty, use platform name
      if (editingSocial.isNew && !editingSocial.data.name.trim()) {
        editingSocial.data.name = socialPlatforms[editingSocial.platformIndex].name;
      }
    }
    
    if (editingSocial.isNew) {
      // Add new social link
      profileConfig.links = [...profileConfig.links, editingSocial.data];
    } else {
      // Update existing link
      const newLinks = [...profileConfig.links];
      newLinks[editingSocial.index] = editingSocial.data;
      profileConfig.links = newLinks;
    }
    
    showSocialEditor = false;
    dispatch('change', profileConfig);
  }
  
  // Function to delete social link
  function deleteSocialLink(index) {
    if (confirm(`Are you sure you want to delete the "${profileConfig.links[index].name}" social link?`)) {
      profileConfig.links = profileConfig.links.filter((_, i) => i !== index);
      dispatch('change', profileConfig);
    }
  }
  
  // Avatar Functions
  
  // Initialize from avatarConfig on mount
  onMount(() => {
    // Initialize avatarConfig if it doesn't exist
    if (!avatarConfig) {
      avatarConfig = {
        avatarList: [],
        homeAvatar: '',
        animationInterval: 3500
      };
    }
    
    // Check if we have a sequence or single avatar
    if (avatarConfig && avatarConfig.avatarList) {
      isAvatarSequence = avatarConfig.avatarList.length > 1;
      avatarCount = avatarConfig.avatarList.length;
      
      // Set the selected avatar index to match the home avatar
      if (isAvatarSequence && avatarConfig.homeAvatar) {
        const homeAvatarPath = avatarConfig.homeAvatar.toString();
        const foundIndex = avatarConfig.avatarList.findIndex(avatar => 
          avatar.toString() === homeAvatarPath
        );
        if (foundIndex >= 0) {
          selectedAvatarIndex = foundIndex;
        }
      }
      
      // Make sure profile avatar matches home avatar
      if (avatarConfig.homeAvatar) {
        profileConfig.avatar = avatarConfig.homeAvatar;
      }
    }
  });

  // Function to update animation interval
  function updateAnimationInterval() {
    dispatch('avatarChange', avatarConfig);
  }
  
  // Function to toggle avatar type
  function toggleAvatarType() {
    isAvatarSequence = !isAvatarSequence;
    if (!isAvatarSequence) {
      // If switching to single avatar, set avatarList to just the home avatar
      avatarConfig.avatarList = [avatarConfig.homeAvatar];
    }
  }
  
  // Function to remove avatar
  function removeAvatar() {
    if (confirm('Are you sure you want to remove your avatar?')) {
      profileConfig.avatar = '';
      dispatch('change', profileConfig);
      
      // Reset avatar config
      avatarConfig.homeAvatar = '';
      avatarConfig.avatarList = [];
      isAvatarSequence = false;
      avatarCount = 0;
      dispatch('avatarChange', avatarConfig);
    }
  }
  
  // Function to select an avatar from the sequence
  function selectAvatar(index) {
    selectedAvatarIndex = index;
    // Update the home avatar
    avatarConfig.homeAvatar = avatarConfig.avatarList[index];
    dispatch('avatarChange', avatarConfig);
  }
  
  // Update selected platform
  function updateSelectedPlatform(event) {
    const selectedIndex = parseInt(event.target.value);
    editingSocial.platformIndex = selectedIndex;
    
    // Pre-fill URL with prefix if it's empty or new
    if (editingSocial.isNew || !editingSocial.data.url) {
      editingSocial.data.url = socialPlatforms[selectedIndex].prefix;
    }
  }

</script>

<div class="profile-config-tab">
  <div class="mb-6">
    <h2 class="text-xl font-semibold text-black/80 dark:text-white/80 mb-4">Profile Settings</h2>
    <p class="text-neutral-600 dark:text-neutral-400 mb-4">
      Configure your personal profile information that appears on your site.
    </p>
  </div>
  
  <!-- Profile Basics -->
  <div class="flex flex-col md:flex-row gap-6 mb-8">
    <!-- Avatar Section - Enhanced with Sequence Support -->
    <div class="md:w-1/3">
      <div class="text-center">
        <h3 class="text-md font-medium text-black/80 dark:text-white/80 mb-3">Profile Image</h3>
        
        <div class="mb-4 flex flex-col items-center">
          <div class="w-32 h-32 bg-neutral-200 dark:bg-neutral-700 rounded-lg overflow-hidden flex items-center justify-center relative">
            {#if avatarConfig.homeAvatar}
              <img 
                src={avatarConfig.homeAvatar} 
                alt="Profile Avatar" 
                class="w-full h-full object-cover" 
              />
            {:else}
              <svg xmlns="http://www.w3.org/2000/svg" class="h-16 w-16 text-neutral-400 dark:text-neutral-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
              </svg>
            {/if}
          </div>

          <!-- Avatar Type Toggle -->
          <div class="mt-3 flex items-center space-x-2">
            <span class="text-sm text-neutral-700 dark:text-neutral-300">Avatar Type:</span>
            <label class="inline-flex items-center">
              <input 
                type="radio" 
                name="avatarType" 
                checked={!isAvatarSequence} 
                on:change={() => isAvatarSequence = false}
                class="h-4 w-4 text-[var(--primary)] border-neutral-300 dark:border-neutral-600" 
              />
              <span class="ml-1 text-sm text-neutral-600 dark:text-neutral-400">Single</span>
            </label>
            <label class="inline-flex items-center">
              <input 
                type="radio" 
                name="avatarType" 
                checked={isAvatarSequence} 
                on:change={() => isAvatarSequence = true}
                class="h-4 w-4 text-[var(--primary)] border-neutral-300 dark:border-neutral-600" 
              />
              <span class="ml-1 text-sm text-neutral-600 dark:text-neutral-400">Sequence</span>
            </label>
          </div>

          <!-- Image Selection Controls -->
          <div class="mt-4 space-y-2">
            <select 
              class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm text-neutral-900 dark:text-neutral-100"
              on:change={(e) => {
                const path = e.target.value;
                if (path) {
                  avatarConfig.homeAvatar = path;
                  avatarConfig.avatarList = [path];
                  profileConfig.avatar = path;
                  dispatch('avatarChange', avatarConfig);
                  dispatch('change', profileConfig);
                }
              }}
            >
              <option value="" class="text-neutral-900 dark:text-neutral-100">Select an avatar image</option>
              <option value="/src/content/avatar/avatar.png" class="text-neutral-900 dark:text-neutral-100">avatar.png</option>
              <option value="/src/content/avatar/avatar2.png" class="text-neutral-900 dark:text-neutral-100">avatar2.png</option>
              <option value="/src/content/avatar/avatar3.png" class="text-neutral-900 dark:text-neutral-100">avatar3.png</option>
              <option value="/src/content/avatar/avatar4.png" class="text-neutral-900 dark:text-neutral-100">avatar4.png</option>
              <option value="/src/content/avatar/avatar5.png" class="text-neutral-900 dark:text-neutral-100">avatar5.png</option>
              <option value="/src/content/avatar/avatar6.png" class="text-neutral-900 dark:text-neutral-100">avatar6.png</option>
            </select>

            {#if isAvatarSequence}
              <div class="space-y-2">
                <h4 class="text-sm font-medium text-black/80 dark:text-white/80">Sequence Images</h4>
                <div class="flex flex-wrap gap-2">
                  {#each avatarConfig.avatarList as avatar, index}
                    <div 
                      class="w-16 h-16 bg-neutral-200 dark:bg-neutral-700 rounded-md overflow-hidden cursor-pointer border-2 border-transparent hover:border-[var(--primary)] transition-colors"
                      class:border-[var(--primary)]={selectedAvatarIndex === index}
                      on:click={() => selectAvatar(index)}
                    >
                      <img src={avatar} alt={`Avatar ${index + 1}`} class="w-full h-full object-cover" />
                    </div>
                  {/each}
                </div>
                
                <select 
                    class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm text-neutral-800 dark:text-neutral-200"
                  on:change={(e) => {
                    const path = e.target.value;
                    if (path && !avatarConfig.avatarList.includes(path)) {
                      avatarConfig.avatarList = [...avatarConfig.avatarList, path];
                      dispatch('avatarChange', avatarConfig);
                    }
                  }}
                >
                  <option value="" class="text-neutral-900 dark:text-neutral-100">Add to sequence...</option>
                  <option value="/src/content/avatar/avatar.png" class="text-neutral-900 dark:text-neutral-100">avatar.png</option>
                  <option value="/src/content/avatar/avatar2.png" class="text-neutral-900 dark:text-neutral-100">avatar2.png</option>
                  <option value="/src/content/avatar/avatar3.png" class="text-neutral-900 dark:text-neutral-100">avatar3.png</option>
                  <option value="/src/content/avatar/avatar4.png" class="text-neutral-900 dark:text-neutral-100">avatar4.png</option>
                  <option value="/src/content/avatar/avatar5.png" class="text-neutral-900 dark:text-neutral-100">avatar5.png</option>
                  <option value="/src/content/avatar/avatar6.png" class="text-neutral-900 dark:text-neutral-100">avatar6.png</option>
                </select>
                
                <div class="mt-4">
                  <label for="animation-interval" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
                    Animation Interval (ms)
                  </label>
                  <input 
                    type="number" 
                    id="animation-interval" 
                    bind:value={avatarConfig.animationInterval}
                    on:input={updateAnimationInterval}
                    min="500"
                    max="10000"
                    step="100"
                    class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm text-neutral-900 dark:text-neutral-100"
                  />
                  <p class="mt-1 text-xs text-neutral-500 dark:text-neutral-400">
                    Time between avatar changes (500ms - 10000ms)
                  </p>
                </div>
              </div>
            {/if}

            <button 
              class="w-full py-1.5 px-3 bg-red-500 hover:bg-red-600 text-white font-medium rounded-md transition-colors text-sm"
              on:click={removeAvatar}
            >
              Remove Avatar
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- Profile Info Section -->
    <div class="md:w-2/3">
      <h3 class="text-md font-medium text-black/80 dark:text-white/80 mb-3">Personal Information</h3>
      
      <div class="space-y-4">
        <div>
          <label for="profile-name" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
            Display Name
          </label>
          <input 
            type="text" 
            id="profile-name" 
            bind:value={profileConfig.name}
            on:input={() => dispatch('change', profileConfig)}
            class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-l text-sm text-neutral-900 dark:text-neutral-100" 
            placeholder="Your Name"
          />
        </div>
        
        <div>
          <label for="profile-bio" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
            Bio / Tagline
          </label>
          <textarea 
            id="profile-bio" 
            bind:value={profileConfig.bio}
            on:input={() => dispatch('change', profileConfig)}
            rows="3"
            class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-l text-sm text-neutral-900 dark:text-neutral-100 resize-none"
            placeholder="A short description about yourself"
          ></textarea>
          <p class="mt-1 text-xs text-neutral-500 dark:text-neutral-400">
            A brief description that appears below your name on your profile
          </p>
        </div>
      </div>
    </div>
  </div>
  
  <!-- Social Links Section -->
  <div class="pt-4 border-t border-neutral-200 dark:border-neutral-700">
    <div class="flex justify-between items-center mb-4">
      <h3 class="text-lg font-medium text-black/80 dark:text-white/80">Social Links</h3>
      <button 
        class="py-1.5 px-3 bg-[var(--primary)] hover:opacity-90 text-white font-medium rounded-md transition-opacity text-sm flex items-center"
        on:click={addSocialLink}
      >
        <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 mr-1" viewBox="0 0 20 20" fill="currentColor">
          <path fill-rule="evenodd" d="M10 5a1 1 0 011 1v3h3a1 1 0 110 2h-3v3a1 1 0 11-2 0v-3H6a1 1 0 110-2h3V6a1 1 0 011-1z" clip-rule="evenodd" />
        </svg>
        Add Social Link
      </button>
    </div>
    
    <div class="social-links-grid grid grid-cols-1 md:grid-cols-2 gap-3 mb-4">
      {#if !profileConfig.links || profileConfig.links.length === 0}
        <div class="col-span-full bg-neutral-50 dark:bg-neutral-800/30 p-4 rounded-lg border border-neutral-200 dark:border-neutral-700 text-center">
          <p class="text-neutral-500 dark:text-neutral-400">No social links configured. Click "Add Social Link" to create one.</p>
        </div>
      {:else}
        {#each profileConfig.links as link, index}
          <div class="social-link-item bg-neutral-50 dark:bg-neutral-800/50 p-3 rounded-lg border border-neutral-200 dark:border-neutral-700 flex items-center justify-between transition hover:border-[var(--primary)]">
            <div class="flex items-center">
              <div class="w-10 h-10 bg-[var(--primary)]/10 rounded-full flex items-center justify-center mr-3">
                <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 text-[var(--primary)]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
                </svg>
              </div>
              <div>
                <h4 class="font-medium text-black/90 dark:text-white/90">{link.name}</h4>
                <div class="text-sm text-neutral-500 dark:text-neutral-400 truncate max-w-[12rem]">
                  {link.url}
                </div>
              </div>
            </div>
            <div class="flex space-x-1">
              <button 
                class="p-1.5 text-neutral-500 hover:text-[var(--primary)] rounded"
                title="Edit Link"
                on:click={() => editSocialLink(index)}
              >
                <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                </svg>
              </button>
              <button 
                class="p-1.5 text-neutral-500 hover:text-red-500 rounded"
                title="Delete Link"
                on:click={() => deleteSocialLink(index)}
              >
                <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                </svg>
              </button>
            </div>
          </div>
        {/each}
      {/if}
    </div>
  </div>
  
  <!-- Social Link Editor Modal -->
  {#if showSocialEditor}
    <div class="fixed inset-0 bg-black/50 dark:bg-black/60 z-50 flex items-center justify-center">
      <div class="bg-white dark:bg-neutral-800 rounded-lg max-w-lg w-full overflow-auto shadow-lg">
        <div class="p-5">
          <h3 class="text-xl font-semibold text-black/80 dark:text-white/80 mb-4">
            {editingSocial.isNew ? 'Add Social Link' : 'Edit Social Link'}
          </h3>
          
          <div class="space-y-4">
            <div>
              <label for="social-platform" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
                Platform
              </label>
              <select 
                id="social-platform" 
                value={editingSocial.platformIndex}
                on:change={updateSelectedPlatform}
                class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-l text-sm text-neutral-900 dark:text-neutral-100"
              >
                <option value="" disabled selected={editingSocial.platformIndex === null} class="text-neutral-900 dark:text-neutral-100">Select a platform...</option>
                {#each socialPlatforms as platform, index}
                  <option value={index} class="text-neutral-900 dark:text-neutral-100">{platform.name}</option>
                {/each}
              </select>
            </div>
            
            <div>
              <label for="social-name" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
                Display Name
              </label>
              <input 
                type="text" 
                id="social-name" 
                bind:value={editingSocial.data.name}
                class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-l text-sm text-neutral-900 dark:text-neutral-100" 
                placeholder="e.g. GitHub, Bluesky, etc."
              />
              <p class="mt-1 text-xs text-neutral-500 dark:text-neutral-400">
                How this link will be labeled (defaults to platform name if left blank)
              </p>
            </div>
            
            <div>
              <label for="social-url" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
                URL
              </label>
              <input 
                type="text" 
                id="social-url" 
                bind:value={editingSocial.data.url}
                class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-l text-sm text-neutral-900 dark:text-neutral-100" 
                placeholder="e.g. https://bluesky.com/username"
              />
            </div>
            
            {#if editingSocial.platformIndex === socialPlatforms.length - 1}
              <div>
                <label for="social-icon" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
                  Icon Class
                </label>
                <input 
                  type="text" 
                  id="social-icon" 
                  bind:value={editingSocial.data.icon}
                  class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-l text-sm text-neutral-900 dark:text-neutral-100" 
                  placeholder="e.g. fa6-brands:github"
                />
                <p class="mt-1 text-xs text-neutral-500 dark:text-neutral-400">
                  For custom icons, use the icon name from your icon set
                </p>
              </div>
            {/if}
          </div>
          
          <div class="flex justify-end space-x-3 mt-6 pt-4 border-t border-neutral-200 dark:border-neutral-700">
            <button 
              type="button"
              class="px-4 py-2 border border-neutral-300 dark:border-neutral-600 text-neutral-700 dark:text-neutral-300 rounded-md hover:bg-neutral-50 dark:hover:bg-neutral-700 transition-colors"
              on:click={() => showSocialEditor = false}
            >
              Cancel
            </button>
            
            <button 
              type="button"
              class="px-4 py-2 bg-[var(--primary)] hover:opacity-90 text-white font-medium rounded-md transition-opacity"
              on:click={saveSocialLink}
              disabled={!editingSocial.data.url || (editingSocial.platformIndex === null && !editingSocial.data.icon)}
            >
              {editingSocial.isNew ? 'Add Link' : 'Save Changes'}
            </button>
          </div>
        </div>
      </div>
    </div>
  {/if}
  
</div>