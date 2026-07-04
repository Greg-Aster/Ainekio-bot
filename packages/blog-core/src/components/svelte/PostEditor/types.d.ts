// Post-related types
interface PostAdvancedOptions {
  avatarImage: string
  backgroundImage: string
  authorName: string
  authorBio: string
  showImageOnPost: boolean
  lang: string
  bannerImage: string
}

interface TimelineData {
  enabled: boolean
  year?: number
  era: string
  location: string
  isKeyEvent: boolean
}

interface BannerData {
  type: string
  videoId: string
  timelineCategory: string
}

interface Post {
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

interface PostMetadata {
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

interface FrontmatterData {
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
  backgroundImage?: string
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

// GitHub related types
interface GitHubServiceConfig {
  owner: string
  repo: string
  branch: string
  configPath: string
  postsPath: string
}

interface GitHubService {
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

interface GitHubInitResult {
  isGitHubAuthenticated: boolean
  loadError: string | null
  missingMethods: string[]
}

interface GitHubOperationResult {
  success: boolean
  error?: string
  filepath?: string
}

// File import/export types
interface FileImportResult {
  fileType: string
  fileName: string
  content: string
  title: string
  post: Post
}

// Custom events for Svelte components
declare namespace svelte.JSX {
  interface HTMLAttributes<T> {
    'on:save-to-github'?: (
      event: CustomEvent<{ post: Post; isDraft: boolean }>,
    ) => void
    'on:auth-success'?: (event: CustomEvent) => void
    'on:auth-logout'?: (event: CustomEvent) => void
    'on:save-success'?: (
      event: CustomEvent<{ post: Post; isDraft: boolean }>,
    ) => void
    'on:save-error'?: (event: CustomEvent<{ error: string }>) => void
    'on:rebuild-success'?: (event: CustomEvent) => void
    'on:rebuild-error'?: (event: CustomEvent<{ error: string }>) => void
    'on:edit'?: (event: CustomEvent<{ postId: string }>) => void
    'on:delete'?: (event: CustomEvent<{ postId: string }>) => void
    'on:refresh'?: (event: CustomEvent) => void
    'on:notification'?: (
      event: CustomEvent<{ message: string; type: 'success' | 'error' }>,
    ) => void
    'on:import-success'?: (event: CustomEvent<FileImportResult>) => void
    'on:clear'?: (event: CustomEvent) => void
    'on:autosave'?: (event: CustomEvent<{ post: Post }>) => void
    'on:authenticate'?: (event: CustomEvent<string>) => void
    'on:cancel'?: (event: CustomEvent) => void
    'on:error'?: (event: CustomEvent<string>) => void
  }
}

// Make these types globally available
declare global {
  // Allow access to these types without importing
  interface Window {
    dispatchEvent(event: Event): boolean
    addEventListener(
      type: string,
      listener: EventListenerOrEventListenerObject,
      options?: boolean | AddEventListenerOptions,
    ): void
    removeEventListener(
      type: string,
      listener: EventListenerOrEventListenerObject,
      options?: boolean | EventListenerOptions,
    ): void
  }
}

export type {
  Post,
  PostMetadata,
  PostAdvancedOptions,
  TimelineData,
  BannerData,
  FrontmatterData,
  GitHubService,
  GitHubServiceConfig,
  GitHubInitResult,
  GitHubOperationResult,
  FileImportResult,
}
