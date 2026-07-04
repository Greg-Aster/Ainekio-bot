// Types for post-related data structures
export type PostAdvancedOptions = {
  avatarImage: string
  authorName: string
  authorBio: string
  showImageOnPost: boolean
  lang: string
  bannerImage: string
}

export type TimelineData = {
  enabled: boolean
  year?: number
  era: string
  location: string
  isKeyEvent: boolean
}

export type BannerData = {
  type: string
  videoId: string
  timelineCategory: string
}

export type Post = {
  title: string
  description: string
  slug: string
  published: string
  image: string
  tags: string | string[]
  category: string
  showAdvancedOptions: boolean
  advanced: PostAdvancedOptions
  timelineData: TimelineData
  banner: BannerData
  content: string
  draft: boolean
  filepath: string
}

export type PostMetadata = {
  id: string
  title: string
  description: string
  slug: string
  published: string
  updated?: string
  tags: string[]
  category: string
  draft: boolean
  filepath: string
  content?: string
  error?: boolean
}

export type FrontmatterData = {
  title?: string
  description?: string
  slug?: string
  published?: string
  updated?: string
  image?: string
  tags?: string[] | string
  category?: string
  draft?: boolean
  avatarImage?: string
  authorName?: string
  authorBio?: string
  showImageOnPost?: boolean
  lang?: string
  bannerImage?: string
  timelineYear?: number
  timelineEra?: string
  timelineLocation?: string
  isKeyEvent?: boolean
  bannerType?: string
  bannerData?: {
    videoId?: string
    category?: string
    image?: string
  }
}

/**
 * Generate a slug from a title
 * @param title - The post title
 * @returns URL-friendly slug
 */
export function generateSlugFromTitle(title: string): string {
  if (!title) return ''

  return title
    .toLowerCase()
    .replace(/[^\w\s-]/g, '')
    .replace(/\s+/g, '-')
    .replace(/-+/g, '-')
    .trim()
}

/**
 * Format a date for display
 * @param dateString - ISO date string
 * @returns Formatted date
 */
export function formatDate(dateString: string): string {
  if (!dateString) return ''

  try {
    const date = new Date(dateString)
    return date.toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    })
  } catch (e) {
    return dateString
  }
}

/**
 * Generate frontmatter for MDX files
 * @param data - Post data
 * @returns Formatted frontmatter
 */
export function generateFrontmatter(data: Post): string {
  const tagsArray = Array.isArray(data.tags)
    ? data.tags
    : data.tags
      ? data.tags.split(',').map(tag => tag.trim())
      : []

  let frontmatter = `---\n`
  frontmatter += `title: "${data.title}"\n`
  frontmatter += `published: ${data.published}\n`
  frontmatter += `description: "${data.description}"\n`

  if (data.image) {
    frontmatter += `image: "${data.image}"\n`
  }

  if (tagsArray.length > 0) {
    frontmatter += `tags: [${tagsArray.map(tag => `"${tag}"`).join(', ')}]\n`
  }

  if (data.category) {
    frontmatter += `category: "${data.category}"\n`
  }

  frontmatter += `draft: ${data.draft}\n`

  // Add advanced fields if enabled
  if (data.showAdvancedOptions) {
    if (data.advanced.avatarImage) {
      frontmatter += `avatarImage: "${data.advanced.avatarImage}"\n`
    }

    if (data.advanced.authorName) {
      frontmatter += `authorName: "${data.advanced.authorName}"\n`
    }

    if (data.advanced.authorBio) {
      frontmatter += `authorBio: "${data.advanced.authorBio}"\n`
    }

    // Add showImageOnPost field
    frontmatter += `showImageOnPost: ${data.advanced.showImageOnPost}\n`

    // Add language field
    if (data.advanced.lang) {
      frontmatter += `lang: "${data.advanced.lang}"\n`
    }
  }

  // Add timeline data if present
  if (data.timelineData && data.timelineData.enabled) {
    frontmatter += `timelineYear: ${data.timelineData.year || new Date().getFullYear()}\n`
    frontmatter += `timelineEra: "${data.timelineData.era}"\n`
    frontmatter += `timelineLocation: "${data.timelineData.location}"\n`
    frontmatter += `isKeyEvent: ${data.timelineData.isKeyEvent}\n`
  }

  // Add banner data if present
  if (data.banner && data.banner.type) {
    frontmatter += `bannerType: "${data.banner.type}"\n`

    if (
      data.banner.type === 'image' &&
      data.advanced &&
      data.advanced.bannerImage
    ) {
      frontmatter += `bannerData:\n`
      frontmatter += `  image: "${data.advanced.bannerImage}"\n`
    } else if (data.banner.type === 'video' && data.banner.videoId) {
      frontmatter += `bannerData:\n`
      frontmatter += `  videoId: "${data.banner.videoId}"\n`
    } else if (
      data.banner.type === 'timeline' &&
      data.banner.timelineCategory
    ) {
      frontmatter += `bannerData:\n`
      frontmatter += `  category: "${data.banner.timelineCategory}"\n`
    }
  }

  frontmatter += `---`
  return frontmatter
}

/**
 * Parse MDX/MD file content with frontmatter
 * @param fileContent - Raw MDX/MD file content
 * @returns Parsed frontmatter and content
 */
export function parseMdxFile(fileContent: string): {
  frontmatter: FrontmatterData
  content: string
} {
  try {
    // Simple frontmatter parser
    const frontmatterMatch = fileContent.match(/---\n([\s\S]*?)\n---/)
    const frontmatter: FrontmatterData = {}
    let content = fileContent

    if (frontmatterMatch) {
      const frontmatterText = frontmatterMatch[1]

      // Extract each line and parse
      frontmatterText.split('\n').forEach(line => {
        const match = line.match(/^(\w+):\s*(.*)$/)
        if (match) {
          let [_, key, rawValue] = match
          let value: string | string[] | boolean = rawValue

          // Handle array values (tags: ["a", "b"])
          if (rawValue.startsWith('[') && rawValue.endsWith(']')) {
            try {
              value = JSON.parse(rawValue.replace(/'/g, '"'))
            } catch (e) {
              value = rawValue
                .slice(1, -1)
                .split(',')
                .map(item => item.trim().replace(/["']/g, ''))
            }
          }

          // Handle boolean values
          else if (rawValue === 'true' || rawValue === 'false') {
            value = rawValue === 'true'
          }

          frontmatter[key as keyof FrontmatterData] = value as any
        }
      })

      // Remove frontmatter from content
      content = fileContent.slice(frontmatterMatch[0].length).trim()
    }

    return { frontmatter, content }
  } catch (error) {
    console.error('Error parsing MDX file:', error)
    return { frontmatter: {}, content: fileContent }
  }
}

/**
 * Create a new empty post object
 * @returns Empty post object with default values
 */
export function createEmptyPost(): Post {
  return {
    title: '',
    description: '',
    slug: '',
    published: new Date().toISOString().split('T')[0],
    image: '',
    tags: '',
    category: '',
    showAdvancedOptions: false,
    advanced: {
      avatarImage: '',
      authorName: '',
      authorBio: '',
      showImageOnPost: false,
      lang: 'en',
      bannerImage: '',
    },
    timelineData: {
      enabled: false,
      year: undefined,
      era: '',
      location: '',
      isKeyEvent: false,
    },
    banner: {
      type: '',
      videoId: '',
      timelineCategory: '',
    },
    content: '',
    draft: true,
    filepath: '',
  }
}

/**
 * Save a post to localStorage cache
 * @param postData - Post data to cache
 * @param githubFolder - GitHub folder path
 * @returns Array of updated cached posts
 */
export function saveCachedPost(
  postData: Post,
  githubFolder: string,
): PostMetadata[] {
  try {
    // Process tags to ensure consistent format
    const tagsArray = Array.isArray(postData.tags)
      ? postData.tags
      : postData.tags
        ? postData.tags.split(',').map(tag => tag.trim())
        : []

    // Get existing cached posts
    const existingPostsStr = localStorage.getItem('cachedPosts')
    const existingPosts: PostMetadata[] = existingPostsStr
      ? JSON.parse(existingPostsStr)
      : []

    // Create a metadata entry for this post
    const postMetadata: PostMetadata = {
      id: `${postData.slug}.mdx`,
      title: postData.title,
      description: postData.description,
      slug: postData.slug,
      published: postData.published,
      updated: new Date().toISOString().split('T')[0],
      tags: tagsArray,
      category: postData.category,
      draft: postData.draft,
      content:
        postData.content.substring(0, 150) +
        (postData.content.length > 150 ? '...' : ''),
      // Use the original filepath if we're editing an existing post
      filepath: postData.filepath || `${githubFolder}/${postData.slug}.mdx`,
    }

    // Check if post already exists (by slug) and update it, otherwise add it
    const existingIndex = existingPosts.findIndex(p => p.slug === postData.slug)
    if (existingIndex !== -1) {
      existingPosts[existingIndex] = postMetadata
    } else {
      existingPosts.push(postMetadata)
    }

    // Save the updated list back to localStorage
    localStorage.setItem('cachedPosts', JSON.stringify(existingPosts))

    // Also save the full post content separately for potential future editing
    localStorage.setItem(
      `fullPost_${postData.slug}`,
      JSON.stringify({
        ...postMetadata,
        content: postData.content,
        advanced: postData.advanced,
        timelineData: postData.timelineData,
        banner: postData.banner,
      }),
    )

    return existingPosts
  } catch (error) {
    console.error('Error saving post to cache:', error)
    throw error
  }
}

/**
 * Get cached posts from localStorage
 * @returns Array of cached posts
 */
export function getCachedPosts(): PostMetadata[] {
  try {
    const cachedPostsStr = localStorage.getItem('cachedPosts')
    if (cachedPostsStr) {
      return JSON.parse(cachedPostsStr)
    }
    return []
  } catch (error) {
    console.error('Error loading cached posts:', error)
    return []
  }
}
