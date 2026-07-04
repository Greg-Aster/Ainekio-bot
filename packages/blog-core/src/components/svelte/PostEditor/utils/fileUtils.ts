import {
  createEmptyPost,
  generateFrontmatter,
  generateSlugFromTitle,
  parseMdxFile,
} from './postUtils'
import type { FrontmatterData, Post } from './postUtils'

export interface FileImportResult {
  fileType: string
  fileName: string
  content: string
  title: string
  post: Post
}

/**
 * Convert plain text to Markdown
 * @param text - Plain text content
 * @returns Converted markdown
 */
export async function convertTextToMarkdown(text: string): Promise<string> {
  // For text files, we'll just add some minimal formatting
  const lines = text.split('\n')
  const inCodeBlock = false
  let inList = false

  const processed = lines.map((line, index) => {
    // Skip empty lines
    if (line.trim() === '') {
      inList = false
      return ''
    }

    // Check for potential headings (simple heuristic)
    if (index === 0 || (index > 0 && lines[index - 1].trim() === '')) {
      if (line.length < 50 && !line.endsWith('.') && !line.includes(':')) {
        return `# ${line}`
      }
    }

    // Check for lists
    if (line.trim().match(/^\d+\.\s/)) {
      inList = true
      return line
    } else if (line.trim().match(/^[\*\-]\s/)) {
      inList = true
      return line
    } else if (inList && line.trim().match(/^\s+/)) {
      return line
    } else {
      inList = false
    }

    // Preserve paragraphs
    return line
  })

  return processed.join('\n')
}

/**
 * Convert HTML to Markdown
 * @param html - HTML content
 * @returns Converted markdown
 */
export async function convertHtmlToMarkdown(html: string): Promise<string> {
  // Basic HTML to Markdown conversion
  let markdown = html

  // Handle headings
  markdown = markdown.replace(/<h1[^>]*>(.*?)<\/h1>/gi, '# $1\n')
  markdown = markdown.replace(/<h2[^>]*>(.*?)<\/h2>/gi, '## $1\n')
  markdown = markdown.replace(/<h3[^>]*>(.*?)<\/h3>/gi, '### $1\n')
  markdown = markdown.replace(/<h4[^>]*>(.*?)<\/h4>/gi, '#### $1\n')
  markdown = markdown.replace(/<h5[^>]*>(.*?)<\/h5>/gi, '##### $1\n')
  markdown = markdown.replace(/<h6[^>]*>(.*?)<\/h6>/gi, '###### $1\n')

  // Handle paragraphs
  markdown = markdown.replace(/<p[^>]*>(.*?)<\/p>/gi, '$1\n\n')

  // Handle line breaks
  markdown = markdown.replace(/<br\s*\/?>/gi, '\n')

  // Handle bold and italic
  markdown = markdown.replace(/<strong[^>]*>(.*?)<\/strong>/gi, '**$1**')
  markdown = markdown.replace(/<b[^>]*>(.*?)<\/b>/gi, '**$1**')
  markdown = markdown.replace(/<em[^>]*>(.*?)<\/em>/gi, '_$1_')
  markdown = markdown.replace(/<i[^>]*>(.*?)<\/i>/gi, '_$1_')

  // Handle links
  markdown = markdown.replace(/<a href="(.*?)"[^>]*>(.*?)<\/a>/gi, '[$2]($1)')

  // Handle images
  markdown = markdown.replace(/<img src="(.*?)"[^>]*>/gi, '![]($1)')

  // Handle lists
  markdown = markdown.replace(/<ul[^>]*>(.*?)<\/ul>/gis, (match, content) => {
    return content.replace(/<li[^>]*>(.*?)<\/li>/gi, '- $1\n')
  })

  markdown = markdown.replace(/<ol[^>]*>(.*?)<\/ol>/gis, (match, content) => {
    let index = 1
    return content.replace(/<li[^>]*>(.*?)<\/li>/gi, () => {
      return `${index++}. $1\n`
    })
  })

  // Handle blockquotes
  markdown = markdown.replace(
    /<blockquote[^>]*>(.*?)<\/blockquote>/gis,
    '> $1\n',
  )

  // Handle code blocks
  markdown = markdown.replace(
    /<pre[^>]*><code[^>]*>(.*?)<\/code><\/pre>/gis,
    '```\n$1\n```\n',
  )

  // Handle inline code
  markdown = markdown.replace(/<code[^>]*>(.*?)<\/code>/gi, '`$1`')

  // Remove remaining HTML tags
  markdown = markdown.replace(/<[^>]*>/g, '')

  // Decode HTML entities
  markdown = markdown.replace(/&lt;/g, '<')
  markdown = markdown.replace(/&gt;/g, '>')
  markdown = markdown.replace(/&amp;/g, '&')
  markdown = markdown.replace(/&quot;/g, '"')
  markdown = markdown.replace(/&#39;/g, "'")

  // Clean up multiple newlines
  markdown = markdown.replace(/\n\s*\n\s*\n/g, '\n\n')

  return markdown
}

/**
 * Extract title from HTML content
 * @param html - HTML content
 * @returns Extracted title or null
 */
export function extractTitleFromHtml(html: string): string | null {
  const titleMatch = html.match(/<title[^>]*>(.*?)<\/title>/i)
  if (titleMatch && titleMatch[1]) {
    return titleMatch[1].trim()
  }

  const h1Match = html.match(/<h1[^>]*>(.*?)<\/h1>/i)
  if (h1Match && h1Match[1]) {
    return h1Match[1].trim().replace(/<[^>]*>/g, '') // Remove any HTML tags inside the h1
  }

  return null
}

/**
 * Convert DOCX to Markdown
 * @param arrayBuffer - DOCX file content
 * @returns Object with title and content
 */
export async function convertDocxToMarkdown(
  arrayBuffer: ArrayBuffer,
): Promise<{ title: string | null; content: string }> {
  try {
    // Check if we're in the browser environment
    if (typeof window === 'undefined') {
      throw new Error(
        'DOCX conversion is only available in browser environments',
      )
    }

    // Dynamically import mammoth only when needed
    let mammoth: any
    try {
      // Try to load mammoth from the installed package
      mammoth = (await import('mammoth')).default
    } catch (importError) {
      console.error('Error importing mammoth:', importError)
      return {
        title: 'Word Document Import Error',
        content:
          "# Word Document Import Error\n\nThere was an error loading the mammoth.js library needed for DOCX conversion.\n\nPlease make sure you've installed it with:\n```\npnpm install mammoth\n```\n\nIf you've already installed it, try restarting your development server.",
      }
    }

    // Once we have mammoth, convert the document
    const result = await mammoth.convertToHtml({ arrayBuffer })
    const html = result.value

    // Extract the title from the document
    let title = null
    const h1Match = html.match(/<h1[^>]*>(.*?)<\/h1>/i)
    if (h1Match && h1Match[1]) {
      title = h1Match[1].trim().replace(/<[^>]*>/g, '')
    }

    // Convert HTML to markdown
    const markdown = await convertHtmlToMarkdown(html)

    return { title, content: markdown }
  } catch (error: any) {
    console.error('Error converting DOCX:', error)
    throw new Error('Failed to convert DOCX file. ' + error.message)
  }
}

/**
 * Generate and download MDX file
 * @param postData - Post data
 */
export async function generateMdxFile(postData: Post): Promise<void> {
  const frontmatter = generateFrontmatter(postData)
  const fullContent = `${frontmatter}\n\n${postData.content}`

  // Create downloadable file
  const blob = new Blob([fullContent], { type: 'text/plain' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${postData.slug}.mdx`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

/**
 * Process file import
 * @param file - Uploaded file
 * @returns Processed content with post data
 */
export async function processFileImport(file: File): Promise<FileImportResult> {
  if (!file) {
    throw new Error('No file selected')
  }

  const fileType = file.name.split('.').pop()?.toLowerCase() || ''

  // Read the file content
  const reader = new FileReader()

  // Define a promise to handle the file reading
  const readFile = new Promise<string | ArrayBuffer>((resolve, reject) => {
    reader.onload = e => resolve(e.target?.result || '')
    reader.onerror = e => reject(new Error('Error reading file'))
  })

  // Start reading the file based on type
  if (fileType === 'docx') {
    reader.readAsArrayBuffer(file)
  } else {
    reader.readAsText(file)
  }

  // Wait for the file to be read
  const result = await readFile

  // Convert the content based on file type
  let converted = ''
  let title = file.name.replace(`.${fileType}`, '')
  let fullPostData: Post | null = null

  switch (fileType) {
    case 'txt':
      converted = await convertTextToMarkdown(result as string)
      break
    case 'html':
      converted = await convertHtmlToMarkdown(result as string)
      title = extractTitleFromHtml(result as string) || title
      break
    case 'md':
    case 'markdown':
    case 'mdx':
      // Check if this is a full MDX file with frontmatter
      if ((result as string).startsWith('---')) {
        const { frontmatter, content } = parseMdxFile(result as string)
        if (frontmatter.title) {
          // We have a full MDX file with frontmatter, extract everything
          const post = createEmptyPost()

          fullPostData = {
            ...post,
            title: frontmatter.title || '',
            description: frontmatter.description || '',
            slug: frontmatter.slug || generateSlugFromTitle(title),
            published:
              frontmatter.published || new Date().toISOString().split('T')[0],
            image: frontmatter.image || '',
            tags: Array.isArray(frontmatter.tags)
              ? frontmatter.tags.join(', ')
              : frontmatter.tags || '',
            category: frontmatter.category || '',
            draft: frontmatter.draft === undefined ? true : frontmatter.draft,
            content: content,
          }

          // Set advanced fields if they exist
          if (
            frontmatter.avatarImage ||
            frontmatter.authorName ||
            frontmatter.authorBio ||
            frontmatter.showImageOnPost !== undefined ||
            frontmatter.lang
          ) {
            fullPostData.showAdvancedOptions = true
            fullPostData.advanced = {
              avatarImage: frontmatter.avatarImage || '',
              authorName: frontmatter.authorName || '',
              authorBio: frontmatter.authorBio || '',
              showImageOnPost:
                frontmatter.showImageOnPost === undefined
                  ? false
                  : (frontmatter.showImageOnPost as boolean),
              lang: frontmatter.lang || 'en',
              bannerImage: frontmatter.bannerImage || '',
            }
          }

          // Set timeline fields if they exist
          if (
            frontmatter.timelineYear ||
            frontmatter.timelineEra ||
            frontmatter.timelineLocation
          ) {
            fullPostData.timelineData = {
              enabled: true,
              year: frontmatter.timelineYear,
              era: frontmatter.timelineEra || '',
              location: frontmatter.timelineLocation || '',
              isKeyEvent: frontmatter.isKeyEvent || false,
            }
          }

          // Set banner fields if they exist
          if (frontmatter.bannerType) {
            fullPostData.banner = {
              type: frontmatter.bannerType || '',
              videoId: frontmatter.bannerData?.videoId || '',
              timelineCategory: frontmatter.bannerData?.category || '',
            }
          }

          converted = content
        } else {
          // There's frontmatter but no title, just use the content
          converted = content
        }
      } else {
        // For plain markdown files without frontmatter
        converted = result as string
        // Try to extract title from first heading
        const mdTitleMatch = (result as string).match(/^#\s+(.+)$/m)
        if (mdTitleMatch && mdTitleMatch[1]) {
          title = mdTitleMatch[1].trim()
        }
      }
      break
    case 'docx':
      const { content, title: extractedTitle } = await convertDocxToMarkdown(
        result as ArrayBuffer,
      )
      converted = content
      title = extractedTitle || title
      break
    default:
      converted = `# Imported Content\n\nOriginal file: ${file.name}\n\n${result}`
  }

  if (!fullPostData) {
    const post = createEmptyPost()

    fullPostData = {
      ...post,
      title: title,
      content: converted,
      slug: generateSlugFromTitle(title),
    }
  }

  return {
    fileType,
    fileName: file.name,
    content: converted,
    title: title,
    post: fullPostData,
  }
}
