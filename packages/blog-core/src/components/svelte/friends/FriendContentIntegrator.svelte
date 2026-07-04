<script>
import { onMount } from 'svelte'
import { postCardConfig } from '@/config/postcard.config'
import {
  getFriendPostsAsEntries,
  isFriendContentEnabled,
} from '@/stores/friendStore'
import { url } from '@/utils/url-utils'

// Using onMount to ensure browser APIs are only accessed client-side
onMount(() => {
  console.log('FriendContentIntegrator mounted')
  console.log('postCardConfig available:', !!postCardConfig)

  function hasValidAuth() {
    const isAuthenticated = localStorage.getItem('isAuthenticated') === 'true'
    const expiresAt = Number(localStorage.getItem('authExpiresAt') || '0')
    if (!isAuthenticated || !expiresAt || Date.now() >= expiresAt) {
      localStorage.removeItem('isAuthenticated')
      localStorage.removeItem('authExpiresAt')
      return false
    }
    return true
  }

  // Check authentication status
  const isAuthenticated = hasValidAuth()

  // Check if friend content is enabled
  const friendContentEnabled = isFriendContentEnabled()

  console.log(
    'Auth status:',
    isAuthenticated,
    'Friend content enabled:',
    friendContentEnabled,
  )

  // Only proceed if authenticated and enabled
  if (!isAuthenticated || !friendContentEnabled) return

  // Create default friend config in case postCardConfig is missing
  const defaultFriendConfig = {
    friendStyling: {
      indicatorType: 'border',
      indicatorColor: '#4f46e5', // Default indigo color
      showFriendAvatar: true,
      avatarSize: 'w-6 h-6',
    },
    attribution: {
      showAttribution: true,
      attributionText: 'From [friendName]',
      linkToFriendSite: true,
    },
    behavior: {
      sortingMethod: 'date',
      mergeWithLocalPosts: true,
    },
  }

  function toSafeExternalUrl(candidate) {
    if (!candidate) return null
    try {
      const parsed = new URL(candidate, window.location.origin)
      if (parsed.protocol === 'http:' || parsed.protocol === 'https:') {
        return parsed.href
      }
    } catch (_error) {
      // Ignore invalid URLs and fall back to safe defaults.
    }
    return null
  }

  // Integration function that reuses your PostCard component
  function integrateFriendPosts() {
    try {
      console.log('Integrating friend posts...')

      // Get the posts container
      const postsContainer = document.getElementById('posts-container')
      if (!postsContainer) {
        console.error('Posts container not found')
        return
      }

      // Remove any existing friend posts to avoid duplicates
      const existingFriendPosts = document.querySelectorAll(
        '[data-friend-content="true"]',
      )
      existingFriendPosts.forEach(post => post.remove())

      // Get friend posts as entry-compatible objects
      const friendEntries = getFriendPostsAsEntries()
      if (friendEntries.length === 0) return

      console.log(
        `Integrating ${friendEntries.length} friend posts with these images:`,
        friendEntries.map(entry => ({
          title: entry.data.title,
          image: entry.data.image,
        })),
      )

      // Find a local PostCard to clone its structure
      const localPostCard = postsContainer.querySelector('.card-base')
      if (!localPostCard) {
        console.error('No local post card found to use as template')
        return
      }

      // Safely get friend config, using defaults if needed
      const friendConfig =
        postCardConfig && postCardConfig.friendPosts
          ? postCardConfig.friendPosts
          : defaultFriendConfig

      console.log('Using friend config:', friendConfig)

      // For each friend post, clone and modify a local post card
      friendEntries.forEach(entry => {
        // Clone the structure of a local post card
        const friendPostElement = localPostCard.cloneNode(true)

        // Add friend-specific attributes and classes
        friendPostElement.setAttribute('data-friend-content', 'true')
        friendPostElement.setAttribute('data-post-id', entry.id)
        friendPostElement.setAttribute('data-post-type', 'friend')
        friendPostElement.setAttribute(
          'data-post-timestamp',
          entry.data.published.getTime(),
        )
        friendPostElement.setAttribute(
          'data-post-date',
          entry.data.published.toISOString().split('T')[0],
        )
        friendPostElement.setAttribute(
          'data-post-category',
          entry.data.category.toLowerCase(),
        )
        friendPostElement.setAttribute(
          'data-post-tags',
          (entry.data.tags || []).join(',').toLowerCase(),
        )

        // Apply the configured indicator style (with safety checks)
        if (
          friendConfig.friendStyling &&
          friendConfig.friendStyling.indicatorType === 'border'
        ) {
          friendPostElement.style.borderLeft = `3px solid ${friendConfig.friendStyling.indicatorColor || '#4f46e5'}`
        } else if (
          friendConfig.friendStyling &&
          friendConfig.friendStyling.indicatorType === 'background'
        ) {
          friendPostElement.style.backgroundColor = `${friendConfig.friendStyling.indicatorColor || '#4f46e5'}20`
        } else if (
          friendConfig.friendStyling &&
          friendConfig.friendStyling.indicatorType === 'badge'
        ) {
          friendPostElement.setAttribute('data-needs-badge', 'true')
        }

        // Update the title link
        const titleLink = friendPostElement.querySelector('a')
        if (titleLink) {
          // Use the correct URL function to handle base path
          titleLink.href =
            toSafeExternalUrl(entry.data.sourceUrl) ||
            url(`/friend/${entry.slug}`)
          titleLink.textContent = entry.data.title
        }

        // Update the publication date
        const dateElement = friendPostElement.querySelector(
          '.text-sm.font-medium',
        )
        if (dateElement) {
          dateElement.textContent = entry.data.published
            .toISOString()
            .split('T')[0]
        }

        // Update category - MODIFIED: Link to friend site instead of local archive
        const categoryLink = friendPostElement.querySelector(
          'a[href*="/category/"]',
        )
        if (categoryLink) {
          // Just link to friend site instead of local archive
          categoryLink.href = toSafeExternalUrl(entry.data.friendUrl) || '#'
          categoryLink.target = '_blank' // Open in new tab
          categoryLink.rel = 'noopener noreferrer'
          categoryLink.textContent = entry.data.category
        }

        // Update tags - MODIFIED: Use spans instead of links to avoid 404s
        const tagsContainer = friendPostElement.querySelector(
          '.hidden.md\\:flex.items-center',
        )
        if (tagsContainer && entry.data.tags && entry.data.tags.length > 0) {
          const tagsWrapper = tagsContainer.querySelector('div:last-child')
          if (tagsWrapper) {
            // Clear existing tags
            tagsWrapper.innerHTML = ''

            // Add each tag
            entry.data.tags.forEach((tag, i) => {
              // Add separator for all but first tag
              if (i > 0) {
                const separator = document.createElement('div')
                separator.className =
                  'mx-1.5 text-[var(--meta-divider)] text-sm'
                separator.textContent = '/'
                tagsWrapper.appendChild(separator)
              }

              // Create tag span (not link) to avoid 404s
              const tagSpan = document.createElement('span')
              tagSpan.className =
                'link-lg transition text-50 text-sm font-medium whitespace-nowrap'
              tagSpan.textContent = tag
              tagsWrapper.appendChild(tagSpan)
            })
          }
        }

        // Update description
        const descriptionEl = friendPostElement.querySelector(
          '.transition.text-75',
        )
        if (descriptionEl && entry.data.description) {
          descriptionEl.textContent = entry.data.description
        }

        // Update word count and reading time
        const statsElements = friendPostElement.querySelectorAll(
          '.text-sm.text-black\\/30 > div',
        )
        if (statsElements.length >= 3) {
          statsElements[0].textContent = `${entry.render().remarkPluginFrontmatter.words} words`
          statsElements[2].textContent = `${entry.render().remarkPluginFrontmatter.minutes} min read`
        }

        // Find the metadata section to place attribution after it
        const metadataSection = friendPostElement.querySelector('.mb-4')

        // Check if we need to add a badge (indicator type) - with safety checks
        if (
          friendConfig.friendStyling &&
          friendConfig.friendStyling.indicatorType === 'badge' &&
          friendPostElement.getAttribute('data-needs-badge') === 'true'
        ) {
          const badge = document.createElement('div')
          badge.className =
            'absolute right-3 top-3 py-1 px-2 rounded-md text-xs font-medium'
          badge.style.backgroundColor =
            friendConfig.friendStyling.indicatorColor || '#4f46e5'
          badge.style.color = 'white'
          badge.textContent = 'Friend'

          // Append badge to post element
          friendPostElement.appendChild(badge)
        }

        // Add friend attribution if enabled - with safety checks
        if (
          metadataSection &&
          friendConfig.attribution &&
          friendConfig.attribution.showAttribution
        ) {
          // Create friend attribution element
          const attribution = document.createElement('div')
          attribution.className = 'flex items-center mb-3'
          const defaultAvatarUrl = url('/assets/avatar/avatar.png')
          const friendName = entry.data.friendName || 'Friend'
          const attributionTemplate =
            friendConfig.attribution.attributionText || 'From [friendName]'

          // Add avatar if enabled - with safety checks
          if (
            friendConfig.friendStyling &&
            friendConfig.friendStyling.showFriendAvatar
          ) {
            const avatarSize =
              friendConfig.friendStyling.avatarSize || 'w-6 h-6'
            const avatarWrapper = document.createElement('div')
            avatarWrapper.className = `${avatarSize} bg-neutral-200 dark:bg-neutral-700 rounded-full overflow-hidden mr-2 flex-shrink-0`

            const avatarImg = document.createElement('img')
            avatarImg.src =
              toSafeExternalUrl(entry.data.friendAvatar) || defaultAvatarUrl
            avatarImg.alt = `${friendName}'s avatar`
            avatarImg.className = 'w-full h-full object-cover'
            avatarImg.onerror = () => {
              avatarImg.onerror = null
              avatarImg.src = defaultAvatarUrl
            }

            avatarWrapper.appendChild(avatarImg)
            attribution.appendChild(avatarWrapper)
          }

          const textNode = document.createElement('span')
          textNode.className = 'text-sm text-neutral-500 dark:text-neutral-400'
          const beforeAfter = attributionTemplate.split('[friendName]')
          const beforeName = beforeAfter[0] || ''
          const afterName = beforeAfter.slice(1).join('[friendName]')
          const friendUrl = toSafeExternalUrl(entry.data.friendUrl)

          textNode.appendChild(document.createTextNode(beforeName))
          if (friendConfig.attribution.linkToFriendSite && friendUrl) {
            const friendLink = document.createElement('a')
            friendLink.href = friendUrl
            friendLink.target = '_blank'
            friendLink.rel = 'noopener noreferrer'
            friendLink.className = 'text-[var(--primary)] hover:underline'
            friendLink.textContent = friendName
            textNode.appendChild(friendLink)
          } else {
            textNode.appendChild(document.createTextNode(friendName))
          }
          textNode.appendChild(document.createTextNode(afterName))

          attribution.appendChild(textNode)

          // Insert after the metadata section
          metadataSection.after(attribution)
        }

        // Update cover image if present - ENHANCED IMAGE HANDLING
        const coverImageWrapper = friendPostElement.querySelector('a.group')

        if (coverImageWrapper && entry.data.image) {
          console.log(
            `Processing image for "${entry.data.title}":`,
            entry.data.image,
          )

          // First try direct access to the img element
          let imageElement = coverImageWrapper.querySelector('img')

          // If not found, look deeper inside any wrappers, with null checks
          if (!imageElement) {
            const firstChild = coverImageWrapper.querySelector('*')
            if (firstChild) {
              imageElement = firstChild.querySelector('img')
            }
          }

          // Still not found, try other selectors
          if (!imageElement) {
            // Try to find image anywhere in the card
            imageElement = friendPostElement.querySelector('img')
          }

          // Still not found, try creating a new img element
          if (!imageElement) {
            console.log('Image element not found, creating new one')
            // Empty the wrapper and create a new image
            imageElement = document.createElement('img')
            imageElement.className = 'w-full h-full object-cover'
            coverImageWrapper.appendChild(imageElement)
          }

          if (imageElement) {
            // Ensure the image is visible and using the post's image
            console.log('Setting image src to:', entry.data.image)
            imageElement.src = entry.data.image
            imageElement.alt = `Cover image for ${entry.data.title}`
            imageElement.style.objectFit = 'cover'
            imageElement.style.width = '100%'
            imageElement.style.height = '100%'

            // Make sure any wrapper is visible
            coverImageWrapper.classList.remove('!hidden')
            coverImageWrapper.style.display = 'block'
          } else {
            console.log('Failed to find or create image element')
          }
        } else {
          console.log(`No image wrapper or data for "${entry.data.title}"`, {
            wrapper: !!coverImageWrapper,
            image: entry.data.image,
          })
        }

        // Add the friend post to the container
        postsContainer.appendChild(friendPostElement)
      })

      // Handle sorting based on configuration - with safety checks
      const allPosts = Array.from(postsContainer.children)
      let sortedPosts = []

      // Check sorting method from config
      const sortingMethod =
        friendConfig.behavior && friendConfig.behavior.sortingMethod
          ? friendConfig.behavior.sortingMethod
          : 'date'

      if (sortingMethod === 'date') {
        // Sort by date (timestamp)
        sortedPosts = allPosts.sort((a, b) => {
          const aTime = Number.parseInt(
            a.getAttribute('data-post-timestamp') || '0',
          )
          const bTime = Number.parseInt(
            b.getAttribute('data-post-timestamp') || '0',
          )
          return bTime - aTime // Descending order (newest first)
        })
      } else if (sortingMethod === 'source') {
        // First local posts, then friend posts grouped by source
        const localPosts = allPosts.filter(
          post => post.getAttribute('data-post-type') !== 'friend',
        )
        const friendPosts = allPosts.filter(
          post => post.getAttribute('data-post-type') === 'friend',
        )

        // Sort each group by date internally
        localPosts.sort((a, b) => {
          const aTime = Number.parseInt(
            a.getAttribute('data-post-timestamp') || '0',
          )
          const bTime = Number.parseInt(
            b.getAttribute('data-post-timestamp') || '0',
          )
          return bTime - aTime
        })

        // Group friend posts by friend name if available
        const friendGroups = {}
        friendPosts.forEach(post => {
          const friendName =
            post.querySelector('.text-[var(--primary)].hover\\:underline')
              ?.textContent || 'Unknown'
          if (!friendGroups[friendName]) {
            friendGroups[friendName] = []
          }
          friendGroups[friendName].push(post)
        })

        // Sort each friend group internally by date
        Object.values(friendGroups).forEach(group => {
          group.sort((a, b) => {
            const aTime = Number.parseInt(
              a.getAttribute('data-post-timestamp') || '0',
            )
            const bTime = Number.parseInt(
              b.getAttribute('data-post-timestamp') || '0',
            )
            return bTime - aTime
          })
        })

        // Combine all posts in order: local posts first, then friend groups
        sortedPosts = [...localPosts, ...Object.values(friendGroups).flat()]
      } else {
        // Default fallback to date sorting
        sortedPosts = allPosts.sort((a, b) => {
          const aTime = Number.parseInt(
            a.getAttribute('data-post-timestamp') || '0',
          )
          const bTime = Number.parseInt(
            b.getAttribute('data-post-timestamp') || '0',
          )
          return bTime - aTime
        })
      }

      // Check if we should merge with local posts - with safety checks
      const mergeWithLocalPosts =
        friendConfig.behavior &&
        typeof friendConfig.behavior.mergeWithLocalPosts !== 'undefined'
          ? friendConfig.behavior.mergeWithLocalPosts
          : true

      if (mergeWithLocalPosts) {
        // Clear and reinsert in sorted order
        while (postsContainer.firstChild) {
          postsContainer.removeChild(postsContainer.firstChild)
        }

        sortedPosts.forEach(post => {
          postsContainer.appendChild(post)
        })
      } else {
        // Separate friend posts from local posts
        // First remove friend posts
        const friendPostElements = document.querySelectorAll(
          '[data-friend-content="true"]',
        )
        friendPostElements.forEach(el => el.remove())

        // Create a container for friend posts
        const friendPostsContainer = document.createElement('div')
        friendPostsContainer.className = 'friend-posts-container mt-8'
        const heading = document.createElement('h2')
        heading.className = 'text-2xl font-bold mb-4 text-black/90 dark:text-white/90'
        heading.textContent = 'Friend Posts'
        friendPostsContainer.appendChild(heading)

        // Get all friend posts
        const friendPosts = sortedPosts.filter(
          post => post.getAttribute('data-post-type') === 'friend',
        )

        // Add friend posts to the friend container
        friendPosts.forEach(post => {
          friendPostsContainer.appendChild(post)
        })

        // Add the friend container after the main posts container
        if (postsContainer.parentNode) {
          postsContainer.parentNode.insertBefore(
            friendPostsContainer,
            postsContainer.nextSibling,
          )
        }
      }

      console.log(
        `Successfully integrated ${friendEntries.length} friend posts`,
      )
    } catch (error) {
      console.error('Error integrating friend posts:', error)
    }
  }

  // Handle friend content toggle events
  function handleFriendContentToggle(e) {
    const enabled = e.detail?.enabled ?? false

    if (enabled && isAuthenticated) {
      integrateFriendPosts()
    } else {
      // Remove friend posts if disabled
      const friendPostElements = document.querySelectorAll(
        '[data-friend-content="true"]',
      )
      friendPostElements.forEach(el => el.remove())
    }
  }

  // Listen for content toggle events
  window.addEventListener('friend-content-toggled', handleFriendContentToggle)

  // Initial integration after a delay to ensure local posts are rendered
  setTimeout(() => {
    try {
      integrateFriendPosts()
    } catch (error) {
      console.error('Error integrating friend posts:', error)
    }
  }, 300)

  // Cleanup function for when component is destroyed
  return () => {
    window.removeEventListener(
      'friend-content-toggled',
      handleFriendContentToggle,
    )
  }
})
</script>

<!-- This component doesn't render anything visible -->
