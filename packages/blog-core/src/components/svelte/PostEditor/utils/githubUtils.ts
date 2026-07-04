import { generateFrontmatter, parseMdxFile } from './postUtils'
import type { Post, PostMetadata } from './postUtils'

export interface GitHubServiceConfig {
  owner: string
  repo: string
  branch: string
  configPath: string
  postsPath: string
}

export interface GitHubService {
  config?: GitHubServiceConfig
  isAuthenticated: () => boolean
  authenticate: (token: string) => boolean
  logout: () => void
  getFile: (path: string) => Promise<{ path: string; content: string }>
  getDirectory: (path: string) => Promise<any[]>
  commitFile: (path: string, content: string, message: string) => Promise<any>
  deleteFile: (path: string, message: string) => Promise<any>
  triggerWorkflow: (workflow: string) => Promise<any>
}

export interface GitHubInitResult {
  isGitHubAuthenticated: boolean
  loadError: string | null
  missingMethods: string[]
}

export interface GitHubOperationResult {
  success: boolean
  error?: string
  filepath?: string
}

/**
 * Initialize GitHub service with validation
 * @param githubService - GitHub service instance
 * @returns Result with status and errors if any
 */
export function initializeGithubService(
  githubService: GitHubService,
): GitHubInitResult {
  // Check GitHub authentication status
  const isGitHubAuthenticated =
    typeof githubService.isAuthenticated === 'function'
      ? githubService.isAuthenticated()
      : false

  // Check if the githubService has all required methods
  const requiredMethods = [
    'isAuthenticated',
    'authenticate',
    'logout',
    'getFile',
    'getDirectory',
    'commitFile',
    'deleteFile',
    'triggerWorkflow',
  ]

  const missingMethods = requiredMethods.filter(
    method => typeof (githubService as any)[method] !== 'function',
  )

  let loadError = null
  if (missingMethods.length > 0) {
    console.warn(
      `GitHub service is missing methods: ${missingMethods.join(', ')}. Some functionality will be limited.`,
    )
    loadError =
      "GitHub service doesn't have all required methods. Please update your GitHub service implementation."
  }

  return {
    isGitHubAuthenticated,
    loadError,
    missingMethods,
  }
}

/**
 * Fetch GitHub posts from repository
 * @param githubService - GitHub service instance
 * @param githubFolder - GitHub folder path
 * @returns Array of posts
 */
export async function fetchGitHubPosts(
  githubService: GitHubService,
  githubFolder: string,
): Promise<PostMetadata[]> {
  try {
    // Check if getDirectory method exists
    if (typeof githubService.getDirectory !== 'function') {
      throw new Error(
        'GitHub service does not support directory listing. Make sure your github-service.js file is up to date.',
      )
    }

    // Get the posts directory contents
    const postsDir = await githubService.getDirectory(githubFolder)

    // Make sure we got an array back
    if (!Array.isArray(postsDir)) {
      throw new Error('Invalid response from GitHub API when listing directory')
    }

    // Process each file that's an MD or MDX file
    const postPromises = postsDir
      .filter(
        item =>
          item &&
          item.type === 'file' &&
          (item.name.endsWith('.md') || item.name.endsWith('.mdx')),
      )
      .map(async item => {
        try {
          const file = await githubService.getFile(
            `${githubFolder}/${item.name}`,
          )
          const { frontmatter, content } = parseMdxFile(file.content)

          return {
            id: item.name,
            slug: item.name.replace(/\.(md|mdx)$/, ''),
            title: frontmatter.title || item.name,
            description: frontmatter.description || '',
            published:
              frontmatter.published || new Date().toISOString().split('T')[0],
            updated: frontmatter.updated,
            tags: Array.isArray(frontmatter.tags)
              ? frontmatter.tags
              : typeof frontmatter.tags === 'string'
                ? [frontmatter.tags]
                : [],
            category: frontmatter.category || '',
            draft: frontmatter.draft === undefined ? false : frontmatter.draft,
            filepath: `${githubFolder}/${item.name}`,
            content:
              content.substring(0, 150) + (content.length > 150 ? '...' : ''),
          } as PostMetadata
        } catch (error) {
          console.error(`Error fetching file ${item.name}:`, error)
          // Return a basic entry with an error indication
          return {
            id: item.name,
            slug: item.name.replace(/\.(md|mdx)$/, ''),
            title: item.name,
            description: 'Error loading post content',
            published: 'Unknown',
            tags: [],
            category: '',
            draft: false,
            filepath: `${githubFolder}/${item.name}`,
            error: true,
          } as PostMetadata
        }
      })

    return await Promise.all(postPromises)
  } catch (error) {
    console.error('Error in fetchGitHubPosts:', error)
    throw error
  }
}

/**
 * Save a post to GitHub
 * @param post - Post data
 * @param isDraft - Whether this is a draft or published post
 * @param githubService - GitHub service instance
 * @param githubFolder - GitHub folder path
 * @param subfolderPath - Optional subfolder path
 * @returns Result with success/error status
 */
export async function savePostToGitHub(
  post: Post,
  isDraft: boolean,
  githubService: GitHubService,
  githubFolder: string,
  subfolderPath?: string,
): Promise<GitHubOperationResult> {
  if (!githubService.isAuthenticated()) {
    return {
      success: false,
      error: 'Please authenticate with GitHub first',
    }
  }

  try {
    // Update draft status
    const postData = {
      ...post,
      draft: isDraft,
    }

    // Create the final content with frontmatter
    const frontmatter = generateFrontmatter(postData)
    const fullContent = `${frontmatter}\n\n${postData.content}`

    // Determine the file path in the repository
    let filePath
    if (post.filepath) {
      // If editing an existing post, use its original filepath
      filePath = post.filepath
    } else if (subfolderPath) {
      filePath = `${githubFolder}/${subfolderPath}/${post.slug}.mdx`
    } else {
      filePath = `${githubFolder}/${post.slug}.mdx`
    }

    // Commit the file to GitHub
    await githubService.commitFile(
      filePath,
      fullContent,
      `${isDraft ? 'Draft' : 'Publish'}: ${post.title}`,
    )

    return {
      success: true,
      filepath: filePath,
    }
  } catch (error: any) {
    console.error('Error saving post to GitHub:', error)

    // Provide more detailed error messages
    let errorMessage
    if (error.message && error.message.includes('401')) {
      errorMessage = 'Authentication failed. Please refresh your GitHub token.'
    } else if (error.message && error.message.includes('404')) {
      errorMessage =
        'Repository or path not found. Check your repository settings.'
    } else {
      errorMessage = `Failed to save to GitHub: ${error.message}`
    }

    return {
      success: false,
      error: errorMessage,
    }
  }
}

/**
 * Trigger a site rebuild via GitHub workflow
 * @param githubService - GitHub service instance
 * @returns Result with success/error status
 */
export async function triggerSiteRebuild(
  githubService: GitHubService,
): Promise<GitHubOperationResult> {
  if (!githubService.isAuthenticated()) {
    return {
      success: false,
      error: 'Please authenticate with GitHub first',
    }
  }

  try {
    // Add a small delay to ensure all commits are processed
    await new Promise(resolve => setTimeout(resolve, 1000))

    // Trigger the GitHub Action workflow for rebuilding the site
    await githubService.triggerWorkflow('deploy.yml')

    return { success: true }
  } catch (error: any) {
    console.error('Error triggering rebuild:', error)

    let errorMessage
    if (error.message && error.message.includes('404')) {
      errorMessage = `Failed to trigger rebuild: Workflow file not found. Make sure 'deploy.yml' exists in your repository's .github/workflows directory.`
    } else {
      errorMessage = `Failed to trigger rebuild: ${error.message}`
    }

    return {
      success: false,
      error: errorMessage,
    }
  }
}
