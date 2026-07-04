<!-- src/components/svelte/ArchiveEnhancer.svelte -->
<script lang="ts">
    import { onMount, onDestroy } from 'svelte';
    import { getFriendPostsAsEntries, isFriendContentEnabled } from '../../stores/friendStore';
    import { url } from '../../utils/url-utils';
    
    // State
    let isAuthenticated = false;
    let friendContentEnabled = false

function hasValidAuth() {
  const authed = localStorage.getItem('isAuthenticated') === 'true'
  const expiresAt = Number(localStorage.getItem('authExpiresAt') || '0')
  if (!authed || !expiresAt || Date.now() >= expiresAt) {
    localStorage.removeItem('isAuthenticated')
    localStorage.removeItem('authExpiresAt')
    return false
  }
  return true
}

function escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

function toSafeExternalUrl(candidate, fallback) {
  try {
    const parsed = new URL(candidate, window.location.origin)
    if (parsed.protocol === 'http:' || parsed.protocol === 'https:') {
      return parsed.href
    }
  } catch (_error) {
    // Ignore and use fallback.
  }
  return fallback
}
    
    function enhanceArchive() {
      // Only proceed if authenticated and enabled
      if (!isAuthenticated || !friendContentEnabled) return;
      
      // Get friend posts
      const friendEntries = getFriendPostsAsEntries();
      if (friendEntries.length === 0) return;
      
      // Find archive panels
      const archivePanels = document.querySelectorAll('.card-base:has(.dash-line)');
      if (archivePanels.length === 0) {
        console.log('No archive panels found on this page');
        return;
      }
      
      // Process each archive panel
      archivePanels.forEach(panel => {
        // Group friend posts by year
        const postsByYear = groupPostsByYear(friendEntries);
        
        // Process each year group
        Object.entries(postsByYear).forEach(([year, posts]) => {
          // Look for an existing year section
          const yearElement = Array.from(panel.querySelectorAll('.text-2xl.font-bold'))
            .find(el => el.textContent === year);
          
          if (yearElement) {
            // Year exists - add posts to the existing year section
            enhanceExistingYearSection(yearElement, posts);
          } else {
            // Year doesn't exist - create a new year section
            createNewYearSection(panel, parseInt(year), posts);
          }
        });
        
        // Re-sort year sections by year (newer first)
        sortYearSections(panel);
      });
      
      console.log('Archive panel enhanced with friend posts');
    }
    
    // Group posts by year
    function groupPostsByYear(posts) {
      const grouped = {};
      
      posts.forEach(post => {
        const year = post.data.published.getFullYear().toString();
        
        if (!grouped[year]) {
          grouped[year] = [];
        }
        
        grouped[year].push(post);
      });
      
      return grouped;
    }
    
    // Add posts to an existing year section
    function enhanceExistingYearSection(yearElement, posts) {
      // Find the parent container
      const yearContainer = yearElement.closest('div');
      if (!yearContainer) return;
      
      // Find the post count element and update it
      const postCountEl = yearContainer.querySelector('.text-50');
      if (postCountEl) {
        // Extract current count
        const countText = postCountEl.textContent || '';
        const countMatch = countText.match(/(\d+)/);
        
        if (countMatch) {
          const currentCount = parseInt(countMatch[1]);
          const newCount = currentCount + posts.length;
          postCountEl.textContent = countText.replace(/(\d+)/, newCount.toString());
        }
      }
      
      // Add each friend post
      posts.forEach(post => {
        addPostElement(yearContainer, post);
      });
    }
    
    // Create a new year section
    function createNewYearSection(panel, year, posts) {
      const yearContainer = document.createElement('div');
      
      // Create year header structure
      yearContainer.innerHTML = `
        <div class="flex flex-row w-full items-center h-[3.75rem]">
          <div class="w-[15%] md:w-[10%] transition text-2xl font-bold text-right text-75">${year}</div>
          <div class="w-[15%] md:w-[10%]">
            <div class="h-3 w-3 bg-none rounded-full outline outline-[var(--primary)] mx-auto -outline-offset-[2px] z-50 outline-3"></div>
          </div>
          <div class="w-[70%] md:w-[80%] transition text-left text-50">${posts.length} posts</div>
        </div>
      `;
      
      // Add each post
      posts.forEach(post => {
        addPostElement(yearContainer, post);
      });
      
      // Add the new year section to the panel
      panel.appendChild(yearContainer);
    }
    
    // Add a post element
    function addPostElement(container, post) {
      // Create post element
      const postElement = document.createElement('a');
      postElement.href = toSafeExternalUrl(post.data.sourceUrl, `/friend-${post.slug || post.id}`)
      postElement.className = 'group btn-plain !block h-10 w-full rounded-lg hover:text-[initial] friend-archive-item';
      postElement.setAttribute('aria-label', post.data.title);
      postElement.setAttribute('data-friend-content', 'true');
      
      // Format date
      const publishDate = post.data.published;
      const month = (publishDate.getMonth() + 1).toString().padStart(2, '0');
      const day = publishDate.getDate().toString().padStart(2, '0');
      const dateFormatted = `${month}-${day}`;
      
      // Format tags
      const tags = post.data.tags || [];
      const formattedTags = tags.map(t => `#${t}`).join(' ')
      const safeTitle = escapeHtml(post.data.title)
      const safeTags = escapeHtml(formattedTags)
      
      // Create post content
      postElement.innerHTML = `
        <div class="flex flex-row justify-start items-center h-full">
          <!-- date -->
          <div class="w-[15%] md:w-[10%] transition text-sm text-right text-50">
            ${dateFormatted}
          </div>
          <!-- dot and line -->
          <div class="w-[15%] md:w-[10%] relative dash-line h-full flex items-center">
            <div class="transition-all mx-auto w-1 h-1 rounded group-hover:h-5
              bg-[oklch(0.5_0.05_var(--hue))] group-hover:bg-[var(--primary)]
              outline outline-4 z-50
              outline-[var(--card-bg)]
              group-hover:outline-[var(--btn-plain-bg-hover)]
              group-active:outline-[var(--btn-plain-bg-active)]"
            ></div>
          </div>
          <!-- post title -->
          <div class="w-[70%] md:max-w-[65%] md:w-[65%] text-left font-bold
            group-hover:translate-x-1 transition-all group-hover:text-[var(--primary)]
            text-75 pr-8 whitespace-nowrap overflow-ellipsis overflow-hidden"
          >
            <span class="inline-block w-2 h-2 bg-[var(--primary)] rounded-full mr-1"></span>
            ${safeTitle}
          </div>
          <!-- tag list -->
          <div class="hidden md:block md:w-[15%] text-left text-sm transition
            whitespace-nowrap overflow-ellipsis overflow-hidden
            text-30"
          >${safeTags}</div>
        </div>
      `;
      
      // Add the post element to the container
      container.appendChild(postElement);
    }
    
    // Sort year sections by year (newest first)
    function sortYearSections(panel) {
      // Get all year sections
      const yearSections = Array.from(panel.children);
      
      // Sort by year (extracting year from the text content)
      yearSections.sort((a, b) => {
        const yearA = parseInt(a.querySelector('.text-2xl.font-bold')?.textContent || '0');
        const yearB = parseInt(b.querySelector('.text-2xl.font-bold')?.textContent || '0');
        return yearB - yearA;
      });
      
      // Re-append in the correct order
      yearSections.forEach(section => {
        panel.appendChild(section);
      });
    }
    
    // Handle friend content toggle events
    function handleFriendContentToggle(e) {
      const event = e as CustomEvent;
      const enabled = event.detail?.enabled ?? false;
      
      if (friendContentEnabled !== enabled) {
        friendContentEnabled = enabled;
        
        if (enabled && isAuthenticated) {
          // Add friend posts to archive
          enhanceArchive();
        } else {
          // Remove friend posts from archive
          document.querySelectorAll('[data-friend-content="true"]').forEach(el => el.remove());
        }
      }
    }
    
    onMount(() => {
      // Check authentication status
      isAuthenticated = hasValidAuth()
      
      // Check if friend content is enabled
      friendContentEnabled = isFriendContentEnabled();
      
      // If authenticated and enabled, enhance archives
      if (isAuthenticated && friendContentEnabled) {
        // Give time for the DOM to be ready
        setTimeout(enhanceArchive, 500);
      }
      
      // Set up for Swup page transitions
      if (typeof window !== 'undefined') {
        // Function to handle Swup page transitions
        const handlePageTransition = () => {
          if (isAuthenticated && friendContentEnabled) {
            // Use a delay to ensure DOM is ready
            setTimeout(enhanceArchive, 500);
          }
        };
        
        // Check if Swup is available
        if (window.swup?.hooks) {
          // Register with Swup hooks for page transitions
          window.swup.hooks.on('page:view', handlePageTransition);
        } else {
          // Set up a listener for when Swup becomes available
          document.addEventListener('swup:enable', () => {
            window.swup.hooks.on('page:view', handlePageTransition);
          });
        }
      }
      
      // Listen for content toggle events
      window.addEventListener('friend-content-toggled', handleFriendContentToggle);
    });
    
    onDestroy(() => {
      // Clean up event listeners
      window.removeEventListener('friend-content-toggled', handleFriendContentToggle);
    });
  </script>
  
  <!-- This component doesn't render anything visible -->