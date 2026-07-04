<script>
  import { createEventDispatcher, onMount } from 'svelte';
  
  // Props
  export let postCardConfig;
  
  // Event dispatcher
  const dispatch = createEventDispatcher();
  
  // Handle changes to configuration
  function handleChange() {
    dispatch('change', postCardConfig);
  }
  
  // Initialize tab functionality
  onMount(() => {
    // Tab functionality
    // Get references to tabs and panels
    const localPostsTab = document.getElementById('local-posts-tab');
    const friendPostsTab = document.getElementById('friend-posts-tab');
    const localPostsPanel = document.getElementById('local-posts-panel');
    const friendPostsPanel = document.getElementById('friend-posts-panel');
    
    // Add click event listeners to tabs
    if (localPostsTab && friendPostsTab && localPostsPanel && friendPostsPanel) {
      localPostsTab.addEventListener('click', () => {
        // Activate local posts tab
        localPostsTab.classList.add('border-[var(--primary)]', 'text-[var(--primary)]');
        localPostsTab.classList.remove('border-transparent', 'text-neutral-500');
        friendPostsTab.classList.remove('border-[var(--primary)]', 'text-[var(--primary)]');
        friendPostsTab.classList.add('border-transparent', 'text-neutral-500');
        
        // Show local posts panel, hide friend posts panel
        localPostsPanel.classList.remove('hidden');
        friendPostsPanel.classList.add('hidden');
      });
      
      friendPostsTab.addEventListener('click', () => {
        // Activate friend posts tab
        friendPostsTab.classList.add('border-[var(--primary)]', 'text-[var(--primary)]');
        friendPostsTab.classList.remove('border-transparent', 'text-neutral-500');
        localPostsTab.classList.remove('border-[var(--primary)]', 'text-[var(--primary)]');
        localPostsTab.classList.add('border-transparent', 'text-neutral-500');
        
        // Show friend posts panel, hide local posts panel
        friendPostsPanel.classList.remove('hidden');
        localPostsPanel.classList.add('hidden');
      });
    }
  });
</script>

<!-- PostCard Settings -->
<div class="bg-neutral-50 dark:bg-neutral-800/50 p-5 rounded-lg border border-neutral-200 dark:border-neutral-700 mb-8">
  <h3 class="text-lg font-medium text-black/80 dark:text-white/80 mb-3">Post Card Settings</h3>
  
  <div class="space-y-6">
    <!-- Local Post Card Tabs -->
    <div class="border-b border-neutral-200 dark:border-neutral-700 mb-4">
      <nav class="flex space-x-8" aria-label="PostCard Tabs">
        <button 
          class="py-2 px-1 border-b-2 border-[var(--primary)] text-[var(--primary)] font-medium"
          id="local-posts-tab"
        >
          Local Posts
        </button>
        <button 
          class="py-2 px-1 border-b-2 border-transparent text-neutral-500 hover:text-neutral-700 dark:hover:text-neutral-300 font-medium"
          id="friend-posts-tab"
        >
          Friend Posts
        </button>
      </nav>
    </div>
    
    <!-- Local Posts Settings -->
    <div id="local-posts-panel">
      <div class="space-y-6">
        <!-- Layout Settings -->
        <div>
          <h4 class="text-md font-medium text-black/80 dark:text-white/80 mb-3">Layout Options</h4>
          
          <div class="space-y-4">
            <div class="flex flex-col space-y-2">
              <label class="text-sm font-medium text-neutral-700 dark:text-neutral-300">
                Image Position
              </label>
              <div class="flex space-x-4">
                <label class="inline-flex items-center">
                  <input 
                    type="radio" 
                    name="localImagePosition" 
                    value="right" 
                    checked={postCardConfig.localPosts.layout.imagePosition === 'right'}
                    on:change={() => {
                      postCardConfig.localPosts.layout.imagePosition = 'right';
                      handleChange();
                    }}
                    class="h-4 w-4 text-[var(--primary)] border-neutral-300 dark:border-neutral-600 focus:ring-[var(--primary)]" 
                  />
                  <span class="ml-2 text-neutral-700 dark:text-neutral-300">Right</span>
                </label>
                
                <label class="inline-flex items-center">
                  <input 
                    type="radio" 
                    name="localImagePosition" 
                    value="top" 
                    checked={postCardConfig.localPosts.layout.imagePosition === 'top'}
                    on:change={() => {
                      postCardConfig.localPosts.layout.imagePosition = 'top';
                      handleChange();
                    }}
                    class="h-4 w-4 text-[var(--primary)] border-neutral-300 dark:border-neutral-600 focus:ring-[var(--primary)]" 
                  />
                  <span class="ml-2 text-neutral-700 dark:text-neutral-300">Top</span>
                </label>
              </div>
            </div>
            
            <div>
              <label for="localImageSize" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
                Image Size (%)
              </label>
              <div class="flex items-center space-x-4">
                <input 
                  type="range" 
                  id="localImageSize" 
                  min="10" 
                  max="50" 
                  step="1"
                  bind:value={postCardConfig.localPosts.layout.imageSizePercentage}
                  on:input={handleChange}
                  class="flex-grow h-2 bg-neutral-200 dark:bg-neutral-700 rounded-lg appearance-none cursor-pointer" 
                />
                <input 
                  type="number" 
                  bind:value={postCardConfig.localPosts.layout.imageSizePercentage}
                  on:input={handleChange}
                  min="10" 
                  max="50" 
                  class="w-16 px-2 py-1 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm transition text-center" 
                />
              </div>
            </div>
            
            <div class="flex items-center">
              <input 
                type="checkbox" 
                id="local-show-enter-button" 
                bind:checked={postCardConfig.localPosts.layout.showEnterButton}
                on:change={handleChange}
                class="h-4 w-4 text-[var(--primary)] border-neutral-300 dark:border-neutral-600 rounded" 
              />
              <label for="local-show-enter-button" class="ml-2 block text-sm text-neutral-700 dark:text-neutral-300">
                Show Enter Button
              </label>
            </div>
          </div>
        </div>
        
        <!-- Styling Settings -->
        <div>
          <h4 class="text-md font-medium text-black/80 dark:text-white/80 mb-3">Styling Options</h4>
          
          <div class="space-y-4">
            <div>
              <label for="localTitleSize" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
                Title Size
              </label>
              <select 
                id="localTitleSize" 
                bind:value={postCardConfig.localPosts.styling.titleSize}
                on:change={handleChange}
                class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-l text-sm text-neutral-900 dark:text-neutral-100"
              >
                <option value="text-xl">Small</option>
                <option value="text-2xl">Medium</option>
                <option value="text-3xl">Large</option>
                <option value="text-4xl">Extra Large</option>
              </select>
            </div>
            
            <div>
              <label for="localDescriptionLines" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
                Description Lines
              </label>
              <select 
                id="localDescriptionLines" 
                bind:value={postCardConfig.localPosts.styling.descriptionLines}
                on:change={handleChange}
                class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-l text-sm text-neutral-900 dark:text-neutral-100"
              >
                <option value={1}>1 Line</option>
                <option value={2}>2 Lines</option>
                <option value={3}>3 Lines</option>
                <option value={4}>4 Lines</option>
              </select>
            </div>
            
            <div class="flex items-center">
              <input 
                type="checkbox" 
                id="local-animation-enabled" 
                bind:checked={postCardConfig.localPosts.styling.animationEnabled}
                on:change={handleChange}
                class="h-4 w-4 text-[var(--primary)] border-neutral-300 dark:border-neutral-600 rounded" 
              />
              <label for="local-animation-enabled" class="ml-2 block text-sm text-neutral-700 dark:text-neutral-300">
                Enable Load Animations
              </label>
            </div>
          </div>
        </div>
        
        <!-- Content Display Options -->
        <div>
          <h4 class="text-md font-medium text-black/80 dark:text-white/80 mb-3">Content Display</h4>
          
          <div class="space-y-3">
            <div class="flex items-center">
              <input 
                type="checkbox" 
                id="local-show-category" 
                bind:checked={postCardConfig.localPosts.content.showCategory}
                on:change={handleChange}
                class="h-4 w-4 text-[var(--primary)] border-neutral-300 dark:border-neutral-600 rounded" 
              />
              <label for="local-show-category" class="ml-2 block text-sm text-neutral-700 dark:text-neutral-300">
                Show Category
              </label>
            </div>
            
            <div class="flex items-center">
              <input 
                type="checkbox" 
                id="local-show-tags" 
                bind:checked={postCardConfig.localPosts.content.showTags}
                on:change={handleChange}
                class="h-4 w-4 text-[var(--primary)] border-neutral-300 dark:border-neutral-600 rounded" 
              />
              <label for="local-show-tags" class="ml-2 block text-sm text-neutral-700 dark:text-neutral-300">
                Show Tags
              </label>
            </div>
            
            <div class="flex items-center">
              <input 
                type="checkbox" 
                id="local-hide-tags-mobile" 
                bind:checked={postCardConfig.localPosts.content.hideTagsOnMobile}
                on:change={handleChange}
                class="h-4 w-4 text-[var(--primary)] border-neutral-300 dark:border-neutral-600 rounded" 
              />
              <label for="local-hide-tags-mobile" class="ml-2 block text-sm text-neutral-700 dark:text-neutral-300">
                Hide Tags on Mobile
              </label>
            </div>
            
            <div class="flex items-center">
              <input 
                type="checkbox" 
                id="local-show-update-date" 
                bind:checked={postCardConfig.localPosts.content.showUpdateDate}
                on:change={handleChange}
                class="h-4 w-4 text-[var(--primary)] border-neutral-300 dark:border-neutral-600 rounded" 
              />
              <label for="local-show-update-date" class="ml-2 block text-sm text-neutral-700 dark:text-neutral-300">
                Show Update Date
              </label>
            </div>
            
            <div class="flex items-center">
              <input 
                type="checkbox" 
                id="local-show-word-count" 
                bind:checked={postCardConfig.localPosts.content.showWordCount}
                on:change={handleChange}
                class="h-4 w-4 text-[var(--primary)] border-neutral-300 dark:border-neutral-600 rounded" 
              />
              <label for="local-show-word-count" class="ml-2 block text-sm text-neutral-700 dark:text-neutral-300">
                Show Word Count
              </label>
            </div>
            
            <div class="flex items-center">
              <input 
                type="checkbox" 
                id="local-show-read-time" 
                bind:checked={postCardConfig.localPosts.content.showReadTime}
                on:change={handleChange}
                class="h-4 w-4 text-[var(--primary)] border-neutral-300 dark:border-neutral-600 rounded" 
              />
              <label for="local-show-read-time" class="ml-2 block text-sm text-neutral-700 dark:text-neutral-300">
                Show Read Time
              </label>
            </div>
          </div>
        </div>
      </div>
    </div>
    
    <!-- Friend Posts Settings (initially hidden, would be shown via JavaScript) -->
    <div id="friend-posts-panel" class="hidden">
      <!-- Friend Post Layout Options -->
      <div class="space-y-6">
        <!-- Layout Settings -->
        <div>
          <h4 class="text-md font-medium text-black/80 dark:text-white/80 mb-3">Layout Options</h4>
          
          <div class="space-y-4">
            <div class="flex flex-col space-y-2">
              <label class="text-sm font-medium text-neutral-700 dark:text-neutral-300">
                Image Position
              </label>
              <div class="flex space-x-4">
                <label class="inline-flex items-center">
                  <input 
                    type="radio" 
                    name="friendImagePosition" 
                    value="right" 
                    checked={postCardConfig.friendPosts.layout.imagePosition === 'right'}
                    on:change={() => {
                      postCardConfig.friendPosts.layout.imagePosition = 'right';
                      handleChange();
                    }}
                    class="h-4 w-4 text-[var(--primary)] border-neutral-300 dark:border-neutral-600 focus:ring-[var(--primary)]" 
                  />
                  <span class="ml-2 text-neutral-700 dark:text-neutral-300">Right</span>
                </label>
                
                <label class="inline-flex items-center">
                  <input 
                    type="radio" 
                    name="friendImagePosition" 
                    value="top" 
                    checked={postCardConfig.friendPosts.layout.imagePosition === 'top'}
                    on:change={() => {
                      postCardConfig.friendPosts.layout.imagePosition = 'top';
                      handleChange();
                    }}
                    class="h-4 w-4 text-[var(--primary)] border-neutral-300 dark:border-neutral-600 focus:ring-[var(--primary)]" 
                  />
                  <span class="ml-2 text-neutral-700 dark:text-neutral-300">Top</span>
                </label>
              </div>
            </div>
            
            <div>
              <label for="friendImageSize" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
                Image Size (%)
              </label>
              <div class="flex items-center space-x-4">
                <input 
                  type="range" 
                  id="friendImageSize" 
                  min="10" 
                  max="50" 
                  step="1"
                  bind:value={postCardConfig.friendPosts.layout.imageSizePercentage}
                  on:input={handleChange}
                  class="flex-grow h-2 bg-neutral-200 dark:bg-neutral-700 rounded-lg appearance-none cursor-pointer" 
                />
                <input 
                  type="number" 
                  bind:value={postCardConfig.friendPosts.layout.imageSizePercentage}
                  on:input={handleChange}
                  min="10" 
                  max="50" 
                  class="w-16 px-2 py-1 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm transition text-center" 
                />
              </div>
            </div>
          </div>
        </div>
        
        <!-- Friend Specific Options -->
        <div>
          <h4 class="text-md font-medium text-black/80 dark:text-white/80 mb-3">Friend Post Styling</h4>
          
          <div class="space-y-4">
            <div>
              <label for="friendIndicatorType" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
                Visual Indicator
              </label>
              <select 
                id="friendIndicatorType" 
                bind:value={postCardConfig.friendPosts.friendStyling.indicatorType}
                on:change={handleChange}
                class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-l text-sm text-neutral-900 dark:text-neutral-100"
              >
                <option value="border">Border</option>
                <option value="badge">Badge</option>
                <option value="background">Background</option>
              </select>
            </div>
            
            <div>
              <label for="friendIndicatorColor" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
                Indicator Color
              </label>
              <input 
                type="text" 
                id="friendIndicatorColor" 
                bind:value={postCardConfig.friendPosts.friendStyling.indicatorColor}
                on:input={handleChange}
                  class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm text-neutral-800 dark:text-neutral-200"
                placeholder="var(--primary)"
              />
            </div>
            
            <div class="flex items-center">
              <input 
                type="checkbox" 
                id="friend-show-avatar" 
                bind:checked={postCardConfig.friendPosts.friendStyling.showFriendAvatar}
                on:change={handleChange}
                class="h-4 w-4 text-[var(--primary)] border-neutral-300 dark:border-neutral-600 rounded" 
              />
              <label for="friend-show-avatar" class="ml-2 block text-sm text-neutral-700 dark:text-neutral-300">
                Show Friend Avatar
              </label>
            </div>
          </div>
        </div>
        
        <!-- Attribution Options -->
        <div>
          <h4 class="text-md font-medium text-black/80 dark:text-white/80 mb-3">Friend Attribution</h4>
          
          <div class="space-y-4">
            <div class="flex items-center">
              <input 
                type="checkbox" 
                id="friend-show-attribution" 
                bind:checked={postCardConfig.friendPosts.attribution.showAttribution}
                on:change={handleChange}
                class="h-4 w-4 text-[var(--primary)] border-neutral-300 dark:border-neutral-600 rounded" 
              />
              <label for="friend-show-attribution" class="ml-2 block text-sm text-neutral-700 dark:text-neutral-300">
                Show Attribution
              </label>
            </div>
            
            <div>
              <label for="friendAttributionText" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
                Attribution Text
              </label>
              <input 
                type="text" 
                id="friendAttributionText" 
                bind:value={postCardConfig.friendPosts.attribution.attributionText}
                on:input={handleChange}
                  class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm text-neutral-800 dark:text-neutral-200"
                placeholder="Shared from [friendName]"
              />
              <p class="mt-1 text-xs text-neutral-500 dark:text-neutral-400">
                Use [friendName] as a placeholder for the friend's name
              </p>
            </div>
            
            <div class="flex items-center">
              <input 
                type="checkbox" 
                id="friend-link-to-site" 
                bind:checked={postCardConfig.friendPosts.attribution.linkToFriendSite}
                on:change={handleChange}
                class="h-4 w-4 text-[var(--primary)] border-neutral-300 dark:border-neutral-600 rounded" 
              />
              <label for="friend-link-to-site" class="ml-2 block text-sm text-neutral-700 dark:text-neutral-300">
                Link to Friend's Site
              </label>
            </div>
          </div>
        </div>
        
        <!-- Integration Behavior -->
        <div>
          <h4 class="text-md font-medium text-black/80 dark:text-white/80 mb-3">Integration Behavior</h4>
          
          <div class="space-y-4">
            <div>
              <label for="friendSortingMethod" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
                Sorting Method
              </label>
              <select 
                id="friendSortingMethod" 
                bind:value={postCardConfig.friendPosts.behavior.sortingMethod}
                on:change={handleChange}
                class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-l text-sm text-neutral-900 dark:text-neutral-100"
              >
                <option value="date">By Date (newest first)</option>
                <option value="source">Group by Source</option>
              </select>
            </div>
            
            <div class="flex items-center">
              <input 
                type="checkbox" 
                id="friend-merge-posts" 
                bind:checked={postCardConfig.friendPosts.behavior.mergeWithLocalPosts}
                on:change={handleChange}
                class="h-4 w-4 text-[var(--primary)] border-neutral-300 dark:border-neutral-600 rounded" 
              />
              <label for="friend-merge-posts" class="ml-2 block text-sm text-neutral-700 dark:text-neutral-300">
                Merge with Local Posts
              </label>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</div>