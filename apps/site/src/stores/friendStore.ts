// src/stores/friendStore.ts
import { derived, get, writable } from 'svelte/store'
import type { Writable } from 'svelte/store'

// Type definitions
export interface FriendPost {
  id: string
  title: string
  slug?: string
  description?: string
  published: string
  updated?: string
  content?: string
  sourceUrl?: string
  url?: string
  tags?: string[]
  friendName?: string
  friendUrl?: string
  friendAvatar?: string | null
  isFriendContent?: boolean
  image?: string
  category?: string
  wordCount?: number
  readingTime?: number
  timelineYear?: number
  timelineEra?: string
  isKeyEvent?: boolean
}

export interface Friend {
  id: string
  name: string
  url: string
  bio?: string
  avatar?: string
  lastSynced?: string
  postCount: number
  posts: FriendPost[]
  isPermanent?: boolean // Flag to differentiate permanent vs temporary friends
}

// Constants for localStorage keys
const FRIENDS_STORAGE_KEY = 'blogFriends'
const FRIEND_CONTENT_ENABLED_KEY = 'friendContentEnabled'

// Create a single unified store for all friends
export const friends: Writable<Friend[]> = writable<Friend[]>([])

// Module-level flag to prevent multiple initializations
let storageInitialized = false

/**
 * Initialize friends from localStorage and set up persistence.
 * Must be called from onMount() to avoid SSR/hydration mismatch errors.
 */
export function initFriendsFromStorage(): void {
  if (storageInitialized) return
  storageInitialized = true

  // Load temporary friends from localStorage
  try {
    const storedFriends = localStorage.getItem(FRIENDS_STORAGE_KEY)
    if (storedFriends) {
      const tempFriends = JSON.parse(storedFriends).map((friend: Friend) => ({
        ...friend,
        isPermanent: false,
      }))
      friends.set(tempFriends)
    }
  } catch (error) {
    console.error('Error loading friends from localStorage:', error)
  }

  // Persist temporary friends to localStorage on store changes
  friends.subscribe(allFriends => {
    const tempFriends = allFriends.filter(friend => !friend.isPermanent)
    localStorage.setItem(FRIENDS_STORAGE_KEY, JSON.stringify(tempFriends))
  })
}

// Helper functions
export function getFriends(
  includePermanent = true,
  includeTemporary = true,
): Friend[] {
  const allFriends = get(friends)
  return allFriends.filter(
    friend =>
      (includePermanent && friend.isPermanent) ||
      (includeTemporary && !friend.isPermanent),
  )
}

export function addFriend(friend: Friend): void {
  friend.isPermanent = friend.isPermanent || false // Default to temporary
  friends.update(currentFriends => [...currentFriends, friend])
}

export function removeFriend(id: string): void {
  friends.update(currentFriends => currentFriends.filter(f => f.id !== id))
}

export function updateFriend(updatedFriend: Friend): void {
  friends.update(currentFriends =>
    currentFriends.map(f =>
      f.id === updatedFriend.id
        ? { ...updatedFriend, isPermanent: f.isPermanent }
        : f,
    ),
  )
}

export function addPermanentFriends(permanentFriends: any[]): void {
  friends.update(currentFriends => {
    // Convert permanent friends to the Friend interface format
    const formattedPermanentFriends = permanentFriends.map(pf => ({
      id:
        pf.id ||
        `perm-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`,
      name: pf.data?.name || 'Unknown Friend',
      url: pf.data?.url || '#',
      bio: pf.data?.bio || '',
      avatar: pf.data?.avatar || '',
      lastSynced: pf.data?.lastSynced || new Date().toISOString(),
      postCount: pf.posts?.length || 0,
      posts: pf.posts || [],
      isPermanent: true, // Mark as permanent
    }))

    // Filter out any existing permanent friends to avoid duplicates
    const tempFriends = currentFriends.filter(f => !f.isPermanent)

    // Combine temporary and permanent friends
    return [...tempFriends, ...formattedPermanentFriends]
  })
}

export function isFriendContentEnabled(): boolean {
  if (typeof window === 'undefined') return true
  // Log this to help debug
  const isEnabled = localStorage.getItem(FRIEND_CONTENT_ENABLED_KEY) !== 'false'
  console.log('Friend content enabled status:', isEnabled)
  return isEnabled
}

export function getFriendContent(): FriendPost[] {
  const allFriends = get(friends)
  let allPosts: FriendPost[] = []

  console.log('getFriendContent called, found', allFriends.length, 'friends')

  // Process all friends, both temporary and permanent
  allFriends.forEach(friend => {
    console.log(
      `Friend "${friend.name}" has ${friend.posts?.length || 0} posts (${friend.isPermanent ? 'permanent' : 'temporary'})`,
    )
    if (friend.posts && friend.posts.length > 0) {
      const posts = friend.posts.map(post => {
        // Calculate word count and reading time if not already provided
        const wordCount =
          post.wordCount ||
          (post.content ? Math.ceil(post.content.split(/\s+/).length) : 100)
        const readingTime =
          post.readingTime || Math.max(1, Math.ceil(wordCount / 200))

        return {
          ...post,
          friendName: friend.name,
          friendUrl: friend.url,
          friendAvatar: friend.avatar,
          isFriendContent: true,
          wordCount,
          readingTime,
        }
      })
      allPosts = [...allPosts, ...posts]
    }
  })

  // Create sample friend post if needed for debugging
  if (allPosts.length === 0 && allFriends.length > 0) {
    console.log('Creating sample friend post for debugging')
    allPosts = [
      {
        id: `sample-post-${Date.now()}`,
        title: 'Sample Friend Post',
        slug: 'sample-post',
        description: 'This is a sample friend post for debugging purposes.',
        published: new Date().toISOString(),
        friendName: 'Debug Friend',
        friendUrl: '#',
        friendAvatar: null,
        isFriendContent: true,
        sourceUrl: '#',
        wordCount: 100,
        readingTime: 1,
      },
    ]
  }

  console.log('Total friend posts found:', allPosts.length)

  // Sort by date (newest first)
  return allPosts.sort(
    (a, b) => new Date(b.published).getTime() - new Date(a.published).getTime(),
  )
}

/**
 * Converts friend posts to a format compatible with local post entries
 * @returns Array of objects that mimic Astro content collection entries
 */
type FriendPostEntry = {
  id: string
  slug: string
  body: string
  data: {
    title: string
    published: Date
    updated: Date | undefined
    tags: string[]
    category: string
    image: string
    description: string
    draft: boolean
    isFriendContent: boolean
    friendName: string | undefined
    friendUrl: string | undefined
    friendAvatar: string | null | undefined
    sourceUrl: string | undefined
  }
  render: () => {
    remarkPluginFrontmatter: { words: number; minutes: number; excerpt: string }
  }
}
export function getFriendPostsAsEntries(): FriendPostEntry[] {
  const friendPosts = getFriendContent()

  // Transform each friend post into a format that matches Astro content entries
  return friendPosts.map(post => {
    // Create a structure that matches your local post entries
    return {
      id: post.id || `friend-${Date.now()}`,
      slug: post.slug || post.id,
      // Astro entry body (will be generated)
      body: post.content || post.description || '',
      // Data object that matches your frontmatter structure
      data: {
        title: post.title,
        published: new Date(post.published),
        updated: post.updated ? new Date(post.updated) : undefined,
        tags: post.tags || [],
        category: post.category || 'Uncategorized',
        image: post.image || '', // Ensure image is passed through
        description: post.description || '',
        draft: false,
        // Add friend-specific data
        isFriendContent: true,
        friendName: post.friendName,
        friendUrl: post.friendUrl,
        friendAvatar: post.friendAvatar,
        sourceUrl: post.sourceUrl,
      },
      render: () => ({
        // This mimics the remarkPluginFrontmatter
        remarkPluginFrontmatter: {
          words: post.wordCount || 100,
          minutes: post.readingTime || 1,
          excerpt: post.description || '',
        },
      }),
    }
  })
}

/**
 * Converts friend posts to timeline events format
 * @returns Array of timeline event objects
 */
type FriendTimelineEvent = {
  slug: string
  title: string
  year: number
  era: string | undefined
  isKeyEvent: boolean
  description: string | undefined
  image: string | undefined
  isFriendContent: boolean
  friendName: string | undefined
  friendUrl: string | undefined
}
export function getFriendPostsAsTimelineEvents(): FriendTimelineEvent[] {
  // Get friend posts
  const friendPosts = getFriendContent()

  // Filter posts that have timeline data
  return friendPosts
    .filter(post => {
      // Only include posts with a timelineYear or that have a published date
      return post.timelineYear || post.published
    })
    .map(post => {
      // Return a timeline event object
      return {
        slug: post.slug || post.id,
        title: post.title,
        year: post.timelineYear || new Date(post.published).getFullYear(),
        era: post.timelineEra,
        isKeyEvent: post.isKeyEvent || false,
        description: post.description,
        image: post.image,
        // Add friend-specific data
        isFriendContent: true,
        friendName: post.friendName,
        friendUrl: post.friendUrl,
      }
    })
}

// Helper to check if a date is valid and not a fallback
export function hasValidDate(dateString: string): boolean {
  // Check if this is a valid, non-fallback date
  if (!dateString) return false

  try {
    const date = new Date(dateString)

    // 1. Check if it's a valid date
    if (isNaN(date.getTime())) return false

    // 2. Check if it's not today's date (which likely means it's a fallback)
    const today = new Date()
    const isToday =
      date.getDate() === today.getDate() &&
      date.getMonth() === today.getMonth() &&
      date.getFullYear() === today.getFullYear()

    // Consider it valid if it's not today (not a fallback)
    return !isToday
  } catch (e) {
    return false
  }
}

// Format URL for consistency
export function formatUrl(url: string): string {
  let cleanUrl = url
  if (!url.startsWith('http://') && !url.startsWith('https://')) {
    cleanUrl = 'https://' + url
  }
  if (cleanUrl.endsWith('/')) {
    cleanUrl = cleanUrl.slice(0, -1)
  }
  return cleanUrl
}

// Validate site and extract author info from HTML
export async function validateSite(url: string): Promise<{
  valid: boolean
  message: string
  siteInfo?: {
    name?: string
    description?: string
    avatar?: string
    url?: string
  }
}> {
  try {
    const formattedUrl = formatUrl(url)
    console.log('Validating site:', formattedUrl)

    // Fetch the homepage HTML
    try {
      const response = await fetch(formattedUrl, {
        method: 'GET',
        headers: { Accept: 'text/html' },
        mode: 'cors',
      })

      if (response.ok) {
        console.log('Site exists, fetched HTML successfully')
        const html = await response.text()

        // Create a DOM parser to extract info from HTML
        const parser = new DOMParser()
        const doc = parser.parseFromString(html, 'text/html')

        // Extract site info from meta tags and other common elements
        const siteName =
          doc
            .querySelector('meta[property="og:site_name"]')
            ?.getAttribute('content') ||
          doc.querySelector('title')?.textContent?.split('|')[0]?.trim() ||
          doc.querySelector('h1')?.textContent?.trim()

        const siteDescription =
          doc
            .querySelector('meta[name="description"]')
            ?.getAttribute('content') ||
          doc
            .querySelector('meta[property="og:description"]')
            ?.getAttribute('content')

        const siteLogo =
          doc
            .querySelector('meta[property="og:image"]')
            ?.getAttribute('content') ||
          doc.querySelector('link[rel="icon"]')?.getAttribute('href')

        // Try to find author info
        const authorName =
          doc
            .querySelector('.author-name, [class*="author"], [id*="author"]')
            ?.textContent?.trim() ||
          doc.querySelector('meta[name="author"]')?.getAttribute('content')

        // Build site info from what we found
        const siteInfo = {
          name: siteName || new URL(formattedUrl).hostname.replace('www.', ''),
          description: siteDescription || '',
          avatar: siteLogo ? new URL(siteLogo, formattedUrl).href : '',
          url: formattedUrl,
        }

        console.log('Extracted site info from HTML:', siteInfo)

        return {
          valid: true,
          message: 'Site exists and information extracted',
          siteInfo,
        }
      } else {
        console.log(`Failed to fetch site HTML: ${response.status}`)
      }
    } catch (error) {
      console.log('Error fetching site HTML:', error)
    }

    // Fallback to just using the hostname
    const hostname = new URL(formattedUrl).hostname
    const siteName = hostname.replace('www.', '')

    return {
      valid: true,
      message: 'Could not extract site info, using defaults',
      siteInfo: {
        name: siteName,
        description: 'No description available',
        avatar: '',
        url: formattedUrl,
      },
    }
  } catch (error) {
    console.error('Error in validateSite:', error)
    return {
      valid: true,
      message: 'Error validating site, but we will try to add it anyway',
      siteInfo: {
        name: new URL(formatUrl(url)).hostname.replace('www.', ''),
        description: 'No description available',
        avatar: '',
        url: formatUrl(url),
      },
    }
  }
}

// Fetch blog posts by checking common Astro endpoints and HTML scraping
export async function fetchFriendContent(
  friendUrl: string,
): Promise<FriendPost[]> {
  try {
    const formattedUrl = formatUrl(friendUrl)
    console.log(`Fetching content from ${formattedUrl}`)

    // Method 1: Try RSS feed first with enhanced CORS handling
    const rssPaths = ['/rss.xml', '/feed.xml', '/feed', '/rss', '/atom.xml']

    for (const path of rssPaths) {
      const rssUrl = `${formattedUrl}${path}`
      console.log('Checking for RSS feed at:', rssUrl)

      try {
        // First approach: Direct fetch with CORS
        try {
          const response = await fetch(rssUrl, {
            method: 'GET',
            headers: {
              Accept: 'application/xml, text/xml, application/rss+xml',
              // Prevent caching
              'Cache-Control': 'no-cache, no-store, must-revalidate',
              Pragma: 'no-cache',
              Expires: '0',
            },
            mode: 'cors',
            // Use a reasonable timeout
            signal: AbortSignal.timeout(3000),
          })

          if (response.ok) {
            const rssText = await response.text()
            console.log(
              `Found RSS feed at ${rssUrl}, size: ${rssText.length} bytes`,
            )

            // Parse RSS XML
            const parser = new DOMParser()
            const rssDoc = parser.parseFromString(rssText, 'application/xml')

            // Check for parsing errors
            const parseError = rssDoc.querySelector('parsererror')
            if (parseError) {
              console.error('XML parsing error:', parseError.textContent)
              continue // Try next path
            }

            // Extract posts from RSS items
            const items = Array.from(rssDoc.querySelectorAll('item, entry'))

            if (items.length > 0) {
              console.log(`Found ${items.length} posts in RSS feed`)

              const mappedPosts = items.map((item, index) => {
                const title =
                  item.querySelector('title')?.textContent ||
                  `Post ${index + 1}`

                // Get link - handle both RSS and Atom formats
                let link = ''
                const linkEl = item.querySelector('link')
                if (linkEl) {
                  // Check if it's an Atom link with href attribute
                  link =
                    linkEl.getAttribute('href') ||
                    linkEl.textContent ||
                    `${formattedUrl}/post-${index}`
                } else {
                  link = `${formattedUrl}/post-${index}`
                }

                const description =
                  item.querySelector('description, summary')?.textContent || ''

                // Handle different date elements in RSS vs Atom
                const pubDate = item.querySelector(
                  'pubDate, published, date',
                )?.textContent
                let published: Date

                if (pubDate) {
                  try {
                    published = new Date(pubDate)
                    if (isNaN(published.getTime())) {
                      // Handle alternative date formats
                      published = new Date()
                    }
                  } catch (e) {
                    published = new Date() // Fallback to current date
                  }
                } else {
                  published = new Date()
                }

                // Get content from different possible elements
                const content =
                  item.querySelector('content\\:encoded, content')
                    ?.textContent || description

                // Try to get image from enclosure
                let image = ''
                const enclosure = item.querySelector('enclosure[type^="image"]')
                if (enclosure && enclosure.getAttribute('url')) {
                  image = enclosure.getAttribute('url') || ''
                } else {
                  // Try to extract first image from content
                  const imgMatch = content.match(
                    /<img[^>]+src=["']([^"']+)["']/i,
                  )
                  if (imgMatch && imgMatch[1]) {
                    // Make sure image is absolute URL
                    image = imgMatch[1].startsWith('http')
                      ? imgMatch[1]
                      : new URL(imgMatch[1], formattedUrl).href
                  }
                }

                // Extract frontmatter if available
                let category = ''
                let tags: string[] = []
                let timelineYear = null
                let timelineEra = null
                let isKeyEvent = false

                // Try to get frontmatter data
                const frontmatter = item.querySelector('frontmatter')
                if (frontmatter) {
                  // Process all child elements as frontmatter fields
                  const categoryEl = frontmatter.querySelector('category')
                  if (categoryEl) {
                    category = categoryEl.textContent || ''
                  }

                  // Check for tags in frontmatter
                  const tagsEl = frontmatter.querySelector('tags')
                  if (tagsEl && tagsEl.textContent) {
                    try {
                      tags = tagsEl.textContent
                        .split(',')
                        .map(t => t.trim())
                        .filter(Boolean)
                    } catch (e) {
                      console.log('Error parsing tags:', e)
                    }
                  }

                  // Check for timeline data
                  const timelineYearEl =
                    frontmatter.querySelector('timelineYear')
                  if (timelineYearEl && timelineYearEl.textContent) {
                    timelineYear = Number.parseInt(
                      timelineYearEl.textContent.trim(),
                    )
                  }

                  const timelineEraEl = frontmatter.querySelector('timelineEra')
                  if (timelineEraEl && timelineEraEl.textContent) {
                    timelineEra = timelineEraEl.textContent.trim()
                  }

                  const isKeyEventEl = frontmatter.querySelector('isKeyEvent')
                  if (isKeyEventEl && isKeyEventEl.textContent) {
                    isKeyEvent =
                      isKeyEventEl.textContent.trim().toLowerCase() === 'true'
                  }

                  // Also check if there's a dedicated image field
                  if (!image) {
                    const imageEl = frontmatter.querySelector('image')
                    if (imageEl && imageEl.textContent) {
                      // Ensure image is absolute URL
                      const imgSrc = imageEl.textContent
                      image = imgSrc.startsWith('http')
                        ? imgSrc
                        : `${formattedUrl}${imgSrc.startsWith('/') ? '' : '/'}${imgSrc}`
                    }
                  }
                }

                // Fallback to standard category elements if not found in frontmatter
                if (!category) {
                  const categoryEl = item.querySelector('category')
                  if (categoryEl) {
                    category = categoryEl.textContent || ''
                  }
                }

                // Fallback to standard item categories if tags not found in frontmatter
                if (tags.length === 0) {
                  const categories = item.querySelectorAll('category')
                  if (categories.length > 0) {
                    tags = Array.from(categories)
                      .map(cat => cat.textContent)
                      .filter(Boolean) as string[]
                  }
                }

                // Extract slug from link
                let slug = ''
                try {
                  const postUrl = new URL(link)
                  const pathParts = postUrl.pathname.split('/').filter(Boolean)
                  slug = pathParts[pathParts.length - 1] || `post-${index}`
                } catch (e) {
                  // If URL parsing fails, extract from link string
                  const pathParts = link.split('/').filter(Boolean)
                  slug = pathParts[pathParts.length - 1] || `post-${index}`
                }

                // Calculate word count and reading time
                const wordCount = content
                  ? Math.ceil(content.split(/\s+/).length)
                  : 100
                const readingTime = Math.max(1, Math.ceil(wordCount / 200))

                return {
                  id: `rss-${slug}`,
                  title,
                  slug,
                  description: description?.substring(0, 150) || '',
                  published: published.toISOString(),
                  content,
                  sourceUrl: link,
                  tags: tags.length > 0 ? tags : [],
                  category: category || '',
                  image,
                  wordCount,
                  readingTime,
                  timelineYear: timelineYear ?? undefined,
                  timelineEra: timelineEra ?? undefined,
                  isKeyEvent,
                }
              })

              // Filter out posts with invalid dates
              const validPosts = mappedPosts.filter(post =>
                hasValidDate(post.published),
              )
              console.log(
                `Filtered out ${mappedPosts.length - validPosts.length} RSS posts with invalid dates`,
              )

              return validPosts
            }
          }
        } catch (directError) {
          console.log(`Direct fetch failed for ${rssUrl}:`, directError)
        }

        // Second approach: Try with no-cors mode to check if resource exists
        try {
          // We can only check if the resource exists with no-cors, not read it
          const response = await fetch(rssUrl, {
            method: 'GET',
            mode: 'no-cors',
            signal: AbortSignal.timeout(2000),
          })

          // If we get here, resource exists, but we can't read it due to CORS
          console.log(`Found RSS at ${rssUrl} but can't read due to CORS`)
        } catch (noCorsError) {
          console.log(`No resource exists at ${rssUrl}`)
        }
      } catch (e) {
        console.log(`Error checking RSS at ${rssUrl}:`, e)
      }
    }

    console.log('No working RSS feeds found')

    // Method 2: Check for common Astro API endpoints
    try {
      const apiUrl = `${formattedUrl}/api/posts.json`
      console.log('Checking for posts API:', apiUrl)

      const response = await fetch(apiUrl, {
        method: 'GET',
        headers: { Accept: 'application/json' },
        mode: 'cors',
      })

      if (response.ok) {
        const data = await response.json()
        console.log('Found posts API, parsing data')

        if (data.posts && Array.isArray(data.posts) && data.posts.length > 0) {
          console.log(`Found ${data.posts.length} posts in API response`)

          return data.posts.map((post: any) => {
            const wordCount = post.wordCount || 100
            const readingTime =
              post.readingTime || Math.max(1, Math.ceil(wordCount / 200))

            return {
              id:
                post.id ||
                post.slug ||
                `post-${Date.now()}-${Math.random().toString(36).substring(2, 7)}`,
              title: post.title || 'Untitled',
              slug: post.slug || '',
              description: post.description || post.excerpt || '',
              published:
                post.published || post.date || new Date().toISOString(),
              content: post.content || post.body || '',
              sourceUrl: post.url || `${formattedUrl}/${post.slug || ''}`,
              tags: post.tags || [],
              category: post.category || '',
              image: post.image || '',
              wordCount,
              readingTime,
              timelineYear: post.timelineYear,
              timelineEra: post.timelineEra,
              isKeyEvent: post.isKeyEvent,
            }
          })
        }
      }
    } catch (error) {
      console.log('Error fetching posts API:', error)
    }

    // Method 3: HTML scraping for Astro/MDX sites
    try {
      console.log(
        'Scraping HTML for blog posts with improved Astro/MDX selectors',
      )

      const response = await fetch(formattedUrl, {
        method: 'GET',
        headers: { Accept: 'text/html' },
        mode: 'cors',
      })

      if (response.ok) {
        const html = await response.text()
        const parser = new DOMParser()
        const doc = parser.parseFromString(html, 'text/html')

        console.log('Extracting data from HTML', doc.title)

        // DIRECT DATE EXTRACTION: First look for elements with data-post-date attribute (PostCard.astro)
        console.log('Looking for data-post-date attributes in the HTML')
        const elementsWithDates = Array.from(
          doc.querySelectorAll('[data-post-date]'),
        )
        console.log(
          `Found ${elementsWithDates.length} elements with data-post-date attributes`,
        )

        // Get all post cards with direct date attributes
        let postElements = Array.from(
          doc.querySelectorAll(
            '.card-base, .local-post, [class*="post-card"], [data-post-date]',
          ),
        )

        // Fallback to generic article selectors if needed
        if (postElements.length === 0) {
          console.log('No post cards found, trying generic article selectors')
          postElements = Array.from(
            doc.querySelectorAll('article, .post, a[href*="/posts/"]'),
          )
        }

        console.log(`Found ${postElements.length} potential post elements`)

        // Track slugs to avoid duplicates
        const processedSlugs = new Set<string>()
        const posts: FriendPost[] = []

        for (const element of postElements) {
          try {
            // DIRECT DATE EXTRACTION - this is the key part!
            const directDateStr = element.getAttribute('data-post-date')
            const directTimestamp = element.getAttribute('data-post-timestamp')
            let published: Date | null = null
            let foundDate = false

            // Method 1: Use data-post-date attribute if available
            if (directDateStr) {
              try {
                published = new Date(directDateStr)
                if (!isNaN(published.getTime())) {
                  foundDate = true
                  console.log(`Found direct date attribute: ${directDateStr}`)
                }
              } catch (e) {
                /* Continue if this fails */
              }
            }

            // Method 2: Use data-post-timestamp attribute if available
            if (!foundDate && directTimestamp) {
              try {
                published = new Date(Number.parseInt(directTimestamp))
                if (!isNaN(published.getTime())) {
                  foundDate = true
                  console.log(
                    `Found direct timestamp attribute: ${directTimestamp}`,
                  )
                }
              } catch (e) {
                /* Continue if this fails */
              }
            }

            // Method 3: Look for time elements inside this post element
            if (!foundDate) {
              const timeEl = element.querySelector('time[datetime]')
              if (timeEl) {
                const dateStr = timeEl.getAttribute('datetime')
                if (dateStr) {
                  try {
                    published = new Date(dateStr)
                    if (!isNaN(published.getTime())) {
                      foundDate = true
                      console.log(
                        `Found time element with datetime: ${dateStr}`,
                      )
                    }
                  } catch (e) {
                    /* Continue if this fails */
                  }
                }
              }
            }

            // Skip this post if we couldn't find a valid date
            if (!foundDate) {
              console.log('Skipping post - no valid date found')
              continue
            }

            // Extract post link
            const linkEl =
              element.tagName === 'A'
                ? element
                : element.querySelector(
                    'a[href*="/posts/"], a[href*="/blog/"], h1 a, h2 a, h3 a, .title a, [class*="title"] a',
                  )

            if (!linkEl) {
              console.log('Skipping post - no link element found')
              continue
            }

            const href = linkEl.getAttribute('href')
            if (!href) {
              console.log('Skipping post - no href attribute found')
              continue
            }

            // Format URL and extract slug
            const fullUrl = href.startsWith('http')
              ? href
              : href.startsWith('/')
                ? `${formattedUrl}${href}`
                : `${formattedUrl}/${href}`

            let slug = ''
            try {
              const url = new URL(fullUrl)
              const pathParts = url.pathname.split('/').filter(Boolean)
              slug = pathParts[pathParts.length - 1] || ''
            } catch (e) {
              const pathParts = href.split('/').filter(Boolean)
              slug = pathParts[pathParts.length - 1] || ''
            }

            // Skip if we've already processed this slug
            if (!slug || processedSlugs.has(slug)) {
              console.log(`Skipping duplicate slug: ${slug}`)
              continue
            }
            processedSlugs.add(slug)

            // Extract title - try multiple possible selectors
            let title = ''

            // First try data attribute if available
            const directTitle = element.getAttribute('data-post-title')
            if (directTitle) {
              title = directTitle
            } else {
              const titleEl = element.querySelector(
                'h1, h2, h3, .title, [class*="title"]',
              )
              if (titleEl) {
                title = titleEl.textContent?.trim() || ''
              } else {
                title =
                  linkEl.getAttribute('title') ||
                  linkEl.textContent?.trim() ||
                  ''
              }
            }

            // Skip posts with generic titles
            if (title.startsWith('Post ') && /^\d+$/.test(title.substring(5))) {
              console.log(`Skipping generic title: ${title}`)
              continue
            }
            if (!title) {
              console.log('Skipping post - no title found')
              continue
            }

            // Extract description - try multiple selectors
            let description = ''

            // First look for a data attribute
            const directDescription = element.getAttribute(
              'data-post-description',
            )
            if (directDescription) {
              description = directDescription
            } else {
              const descEl = element.querySelector(
                '.text-75, p, .description, [class*="description"], [class*="excerpt"]',
              )
              if (descEl) {
                description = descEl.textContent?.trim() || ''
              }
            }

            // Extract metadata - categories and tags
            let category = ''
            let tags: string[] = []

            // Try data attributes first
            const directCategory = element.getAttribute('data-post-category')
            if (directCategory) {
              category = directCategory
            } else {
              // Look for category and tag links
              const categoryEl = element.querySelector('a[href*="/category/"]')
              if (categoryEl) {
                category = categoryEl.textContent?.trim() || ''
              } else {
                // Try to extract from slug
                const slugParts = slug.split('-')
                if (slugParts.length > 1) {
                  category = slugParts[0].toUpperCase()
                }
              }
            }

            // Try data attribute for tags
            const directTags = element.getAttribute('data-post-tags')
            if (directTags) {
              tags = directTags
                .split(',')
                .map(t => t.trim())
                .filter(Boolean)
            } else {
              // Look for tags
              const tagLinks = element.querySelectorAll('a[href*="/tag/"]')
              if (tagLinks.length > 0) {
                tags = Array.from(tagLinks)
                  .map(el => el.textContent?.trim() || '')
                  .filter(Boolean) as string[]
              }
            }

            // DIRECT IMAGE EXTRACTION - multiple methods similar to date extraction
            let image = ''

            // Method 1: Try to extract image from post data attributes
            const directImage = element.getAttribute('data-post-image')
            if (directImage) {
              // Ensure absolute URL
              image = directImage.startsWith('http')
                ? directImage
                : directImage.startsWith('/')
                  ? `${formattedUrl}${directImage}`
                  : `${formattedUrl}/${directImage}`
              console.log(`Found direct image attribute: ${image}`)
            }

            // Method 2: Try to extract image from HTML content (images specifically inside this post element)
            if (!image) {
              // First, look for specific post image containers
              const postImageContainer = element.querySelector(
                '.post-image, .featured-image, [class*="cover"], [class*="banner"], [id="post-cover"], [id*="cover"], [id*="banner"]',
              )
              if (postImageContainer) {
                const imgEl = postImageContainer.querySelector('img')
                if (imgEl) {
                  const src = imgEl.getAttribute('src')
                  if (src) {
                    // Ensure absolute URL
                    image = src.startsWith('http')
                      ? src
                      : src.startsWith('/')
                        ? `${formattedUrl}${src}`
                        : `${formattedUrl}/${src}`
                    console.log(`Found post image container: ${image}`)
                  }
                }
              }
            }

            // Method 3: Look for specific meta tags inside the post element
            if (!image) {
              const metaImage = element.querySelector(
                'meta[property="og:image"], meta[name="image"], meta[name="twitter:image"]',
              )
              if (metaImage) {
                const src = metaImage.getAttribute('content')
                if (src) {
                  // Ensure absolute URL
                  image = src.startsWith('http')
                    ? src
                    : src.startsWith('/')
                      ? `${formattedUrl}${src}`
                      : `${formattedUrl}/${src}`
                  console.log(`Found post meta image: ${image}`)
                }
              }
            }

            // Method 4: Try parsing frontmatter in the HTML source
            if (!image) {
              // If we have a title, try to find corresponding frontmatter in the HTML
              const title = element
                .querySelector('h1, h2, h3, .title, [class*="title"]')
                ?.textContent?.trim()
              if (title) {
                // Extract all frontmatter sections from the HTML
                const frontmatterMatches = html.match(/---\s*([\s\S]*?)\s*---/g)
                if (frontmatterMatches) {
                  for (const match of frontmatterMatches) {
                    const frontmatter = match.replace(/---/g, '').trim()
                    // Check if this frontmatter section contains the title
                    if (
                      frontmatter.includes(`title: "${title}"`) ||
                      frontmatter.includes(`title: '${title}'`)
                    ) {
                      // Extract image path
                      const imageMatch = frontmatter.match(
                        /image:\s*["']?([^"'\n]+)["']?/,
                      )
                      if (imageMatch && imageMatch[1]) {
                        const imagePath = imageMatch[1].trim()
                        // Ensure absolute URL
                        image = imagePath.startsWith('http')
                          ? imagePath
                          : imagePath.startsWith('/')
                            ? `${formattedUrl}${imagePath}`
                            : `${formattedUrl}/${imagePath}`
                        console.log(`Found image in frontmatter: ${image}`)
                        break
                      }
                    }
                  }
                }
              }
            }

            // Method 5: Only now check for site-wide og:image
            if (!image) {
              const ogImageMeta = doc.querySelector('meta[property="og:image"]')
              if (ogImageMeta) {
                const metaImage = ogImageMeta.getAttribute('content')
                if (metaImage) {
                  // Extra check to skip known site banner images
                  if (
                    !metaImage.includes('/assets/banner/') &&
                    !metaImage.includes('/images/banner/')
                  ) {
                    // Ensure absolute URL
                    image = metaImage.startsWith('http')
                      ? metaImage
                      : metaImage.startsWith('/')
                        ? `${formattedUrl}${metaImage}`
                        : `${formattedUrl}/${metaImage}`
                    console.log(`Found og:image meta tag: ${image}`)
                  } else {
                    console.log(`Skipping site banner image: ${metaImage}`)
                  }
                }
              }
            }

            // Method 6: Fallback - look for any image
            if (!image) {
              const imgEl = element.querySelector('img')
              if (imgEl) {
                const src = imgEl.getAttribute('src')
                if (src) {
                  // Ensure absolute URL
                  image = src.startsWith('http')
                    ? src
                    : src.startsWith('/')
                      ? `${formattedUrl}${src}`
                      : `${formattedUrl}/${src}`
                  console.log(`Found generic image: ${image}`)
                }
              }
            }

            // Log image extraction result
            if (image) {
              console.log(`Successfully extracted image: ${image}`)
            } else {
              console.log('No image found for this post')
            }

            // Extract word count and reading time from data attributes if available
            let wordCount = 100 // Default
            let readingTime = 1 // Default

            const directWordCount = element.getAttribute('data-post-words')
            if (directWordCount && !isNaN(Number.parseInt(directWordCount))) {
              wordCount = Number.parseInt(directWordCount)
            } else {
              // Estimate from description if available
              wordCount = description
                ? Math.ceil(description.split(/\s+/).length) * 3
                : 100
            }

            const directReadingTime = element.getAttribute('data-post-minutes')
            if (
              directReadingTime &&
              !isNaN(Number.parseInt(directReadingTime))
            ) {
              readingTime = Number.parseInt(directReadingTime)
            } else {
              readingTime = Math.max(1, Math.ceil(wordCount / 200))
            }

            // Create post object with enhanced metadata
            posts.push({
              id: `scraped-${slug}`,
              title,
              slug,
              description: description?.substring(0, 150) || '',
              published: published!.toISOString(),
              content: '', // We don't fetch full content at list level
              sourceUrl: fullUrl,
              tags,
              category,
              image,
              wordCount,
              readingTime,
            })

            console.log(
              `Successfully extracted post: "${title}" with date ${published!.toISOString()}`,
            )
          } catch (err) {
            console.error('Error processing post element:', err)
          }
        }

        console.log(
          `Successfully extracted ${posts.length} posts with metadata`,
        )

        // Only return posts that have valid dates
        const validPosts = posts.filter(post => hasValidDate(post.published))
        console.log(`Filtered to ${validPosts.length} posts with valid dates`)

        // Return posts with metadata
        return validPosts.length > 0 ? validPosts : []
      }
    } catch (error) {
      console.log('Error with enhanced HTML scraping:', error)
    }

    // If we get here, we couldn't find any posts
    console.log(
      'Could not find any posts, creating a fallback placeholder post',
    )

    // Return empty array since we don't want to create fallback posts anymore
    return []
  } catch (error) {
    console.error('Unexpected error in fetchFriendContent:', error)

    // Return empty array in case of error
    return []
  }
}

// Generate markdown content for a friend
export function generateFriendMarkdown(friend: Friend): string {
  return `---
name: "${friend.name}"
url: "${friend.url}"
bio: "${friend.bio || ''}"
avatar: "${friend.avatar || ''}"
lastSynced: "${friend.lastSynced || new Date().toISOString()}"
---

# ${friend.name}

Friend site: [${friend.url}](${friend.url})

${friend.bio ? `Bio: ${friend.bio}` : ''}

Last synced: ${friend.lastSynced ? new Date(friend.lastSynced).toLocaleString() : 'Never'}
`
}

// Download a friend as a markdown file
export function downloadFriendAsMarkdown(friend: Friend): { filename: string } {
  // Create filename
  const sanitizedName = friend.name.toLowerCase().replace(/[^a-z0-9]/g, '-')
  const filename = `${sanitizedName}.md`

  // Generate markdown content
  const markdown = generateFriendMarkdown(friend)

  // Create download
  const blob = new Blob([markdown], { type: 'text/markdown' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)

  return { filename }
}

// For backwards compatibility - these functions call the unified store functions
export const temporaryFriends = {
  set: (tempFriends: Friend[]): void => {
    const currentFriends = get(friends)
    const permanentFriends = currentFriends.filter(f => f.isPermanent)
    friends.set([
      ...permanentFriends,
      ...tempFriends.map(f => ({ ...f, isPermanent: false })),
    ])
  },
  update: (updateFn: (tempFriends: Friend[]) => Friend[]): void => {
    friends.update(allFriends => {
      const tempFriends = allFriends.filter(f => !f.isPermanent)
      const permanentFriends = allFriends.filter(f => f.isPermanent)
      const updatedTempFriends = updateFn(tempFriends).map(f => ({
        ...f,
        isPermanent: false,
      }))
      return [...permanentFriends, ...updatedTempFriends]
    })
  },
  subscribe: (callback: (value: Friend[]) => void): (() => void) => {
    return friends.subscribe(allFriends => {
      callback(allFriends.filter(f => !f.isPermanent))
    })
  },
}

export const permanentFriends = {
  set: (permFriends: any[]): void => {
    addPermanentFriends(permFriends)
  },
  update: (updateFn: (permFriends: any[]) => any[]): void => {
    // This is more complex with the new system, but maintaining for compatibility
    friends.update(allFriends => {
      const tempFriends = allFriends.filter(f => !f.isPermanent)
      const permFriends = allFriends.filter(f => f.isPermanent)

      // Convert to old format for the update function
      const oldFormat = permFriends.map(pf => ({
        id: pf.id,
        data: {
          name: pf.name,
          url: pf.url,
          bio: pf.bio || '',
          avatar: pf.avatar || '',
          lastSynced: pf.lastSynced,
        },
        posts: pf.posts || [],
      }))

      // Update using the provided function
      const updatedPermFriendsOldFormat = updateFn(oldFormat)

      // Convert back to new format
      const updatedPermFriends = updatedPermFriendsOldFormat.map(pf => ({
        id: pf.id,
        name: pf.data?.name || 'Unknown',
        url: pf.data?.url || '#',
        bio: pf.data?.bio || '',
        avatar: pf.data?.avatar || '',
        lastSynced: pf.data?.lastSynced || new Date().toISOString(),
        postCount: pf.posts?.length || 0,
        posts: pf.posts || [],
        isPermanent: true,
      }))

      return [...tempFriends, ...updatedPermFriends]
    })
  },
  subscribe: (callback: (value: any[]) => void): (() => void) => {
    return friends.subscribe(allFriends => {
      // Convert to old format for the callback
      const permFriends = allFriends
        .filter(f => f.isPermanent)
        .map(pf => ({
          id: pf.id,
          data: {
            name: pf.name,
            url: pf.url,
            bio: pf.bio || '',
            avatar: pf.avatar || '',
            lastSynced: pf.lastSynced,
          },
          posts: pf.posts || [],
        }))

      callback(permFriends)
    })
  },
}
