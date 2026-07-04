// src/lib/github-service.ts
interface GitHubConfig {
  owner: string
  repo: string
  branch: string
  configPath: string
  postsPath: string
}

export class GitHubService {
  private token: string | null = null
  private config: GitHubConfig

  constructor(config: GitHubConfig) {
    this.config = config
    if (typeof window !== 'undefined') {
      this.token = sessionStorage.getItem('github_token')
    }
  }

  isAuthenticated(): boolean {
    return this.token !== null
  }

  authenticate(token: string): boolean {
    if (!token) return false
    this.token = token
    if (typeof window !== 'undefined') {
      sessionStorage.setItem('github_token', token)
    }
    return true
  }

  logout(): void {
    this.token = null
    if (typeof window !== 'undefined') {
      sessionStorage.removeItem('github_token')
    }
  }

  private async githubRequest(url: string, options: RequestInit = {}) {
    if (!this.token) throw new Error('Authentication required')

    const response = await fetch(url, {
      ...options,
      headers: {
        Authorization: `token ${this.token}`,
        Accept: 'application/vnd.github.v3+json',
        ...options.headers,
      },
    })

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}))
      throw new Error(
        `GitHub API error: ${response.status} - ${errorData.message || response.statusText}`,
      )
    }

    return response
  }

  async getFile(
    path: string,
  ): Promise<{ content: string; sha: string } | null> {
    try {
      const encodedPath = encodeURIComponent(path)
      const response = await this.githubRequest(
        `https://api.github.com/repos/${this.config.owner}/${this.config.repo}/contents/${encodedPath}?ref=${this.config.branch}`,
      )

      const data = await response.json()
      return { content: atob(data.content), sha: data.sha }
    } catch (error) {
      if ((error as Error).message.includes('404')) return null
      throw error
    }
  }

  async getDirectory(
    path: string,
  ): Promise<Array<{ name: string; type: 'file' | 'dir' }>> {
    const encodedPath = encodeURIComponent(path)
    const response = await this.githubRequest(
      `https://api.github.com/repos/${this.config.owner}/${this.config.repo}/contents/${encodedPath}?ref=${this.config.branch}`,
    )

    const data = await response.json()
    if (!Array.isArray(data)) throw new Error(`${path} is not a directory`)

    return data.map((item: any) => ({
      name: item.name,
      type: item.type === 'dir' ? 'dir' : 'file',
      path: item.path,
    }))
  }

  async commitFile(
    path: string,
    content: string,
    message: string,
  ): Promise<boolean> {
    const encodedPath = encodeURIComponent(path)
    const existingFile = await this.getFile(path)

    // Check for existing content
    if (existingFile?.content === content) {
      console.log('No changes detected, skipping commit')
      return true
    }

    // Properly encode Unicode content
    const encodedContent = btoa(unescape(encodeURIComponent(content)))

    const body: any = {
      message,
      content: encodedContent,
      branch: this.config.branch,
    }

    if (existingFile) body.sha = existingFile.sha

    await this.githubRequest(
      `https://api.github.com/repos/${this.config.owner}/${this.config.repo}/contents/${encodedPath}`,
      {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      },
    )

    return true
  }

  async deleteFile(path: string, message: string): Promise<boolean> {
    const encodedPath = encodeURIComponent(path)
    const existingFile = await this.getFile(path)
    if (!existingFile) throw new Error('File not found')

    await this.githubRequest(
      `https://api.github.com/repos/${this.config.owner}/${this.config.repo}/contents/${encodedPath}`,
      {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message,
          sha: existingFile.sha,
          branch: this.config.branch,
        }),
      },
    )

    return true
  }

  async triggerWorkflow(workflowId: string): Promise<boolean> {
    await this.githubRequest(
      `https://api.github.com/repos/${this.config.owner}/${this.config.repo}/actions/workflows/${workflowId}/dispatches`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ref: this.config.branch,
          inputs: { source: 'post-editor' },
        }),
      },
    )

    return true
  }

  // Helper methods for specific content types
  async saveConfig(fileName: string, content: string): Promise<boolean> {
    const path = `${this.config.configPath}/${fileName}`
    return this.commitFile(path, content, `Update ${fileName} configuration`)
  }

  async savePost(
    slug: string,
    content: string,
    isDraft = false,
  ): Promise<boolean> {
    const folder = isDraft ? 'drafts' : 'posts'
    const path = `${this.config.postsPath}/${folder}/${slug}.mdx`
    return this.commitFile(
      path,
      content,
      `${isDraft ? 'Save draft' : 'Publish'}: ${slug}`,
    )
  }
}

export function createGitHubService(
  config?: Partial<GitHubConfig>,
): GitHubService {
  const defaultConfig: GitHubConfig = {
    owner: import.meta.env.PUBLIC_GITHUB_OWNER || '',
    repo: import.meta.env.PUBLIC_GITHUB_REPO || '',
    branch: import.meta.env.PUBLIC_GITHUB_BRANCH || 'main',
    configPath: 'src/config',
    postsPath: 'src/content',
  }

  return new GitHubService({ ...defaultConfig, ...config })
}
