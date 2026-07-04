// src/pages/rss.xml.ts
import { siteConfig } from '@/config/config'
import rss from '@astrojs/rss'
import { getSortedPosts } from '@utils/content-utils'
import type { APIContext } from 'astro'
import MarkdownIt from 'markdown-it'
import sanitizeHtml from 'sanitize-html'
import { createCORSResponse, handleCORS } from '../middleware/cors'

const parser = new MarkdownIt()

function stripMdxSyntax(body: string): string {
  return body
    .replace(/^import\s+.*?['"][^'"]*['"]\s*;?\s*$/gm, '')   // import statements
    .replace(/^export\s+.*$/gm, '')                            // export statements
    .replace(/<[A-Z][A-Za-z0-9]*[^>]*\/>/g, '')               // self-closing JSX <Foo />
    .replace(/<[A-Z][A-Za-z0-9]*[^>]*>[\s\S]*?<\/[A-Z][A-Za-z0-9]*>/g, '') // JSX blocks
    .replace(/\{\/\*[\s\S]*?\*\/\}/g, '')                      // JSX comments {/* */}
    .replace(/\{[^}]*\}/g, '')                                 // JSX expressions {...}
    .replace(/\n{3,}/g, '\n\n')
    .trim()
}

export async function GET(context: APIContext): Promise<Response> {
  // Handle preflight requests
  const corsResponse = handleCORS(context)
  if (corsResponse) return corsResponse

  // Get posts
  const blog = await getSortedPosts()

  // Generate RSS feed
  const response = await rss({
    title: siteConfig.title,
    description: siteConfig.subtitle || 'No description',
    site:
      context.site ??
      (context.url ? context.url.origin : 'https://ainek.io'),
    items: blog.map(post => {
      return {
        title: post.data.title,
        pubDate: post.data.published,
        description: post.data.description || '',
        link: `/posts/${post.slug}/`,
        content: sanitizeHtml(parser.render(stripMdxSyntax(post.body || '')), {
          allowedTags: sanitizeHtml.defaults.allowedTags.concat(['img']),
        }),
        // Add explicit frontmatter data
        customData: `
        <frontmatter>
          <published>${post.data.published.toISOString()}</published>
          ${post.data.updated ? `<updated>${post.data.updated.toISOString()}</updated>` : ''}
          ${post.data.tags && post.data.tags.length > 0 ? `<tags>${post.data.tags.join(',')}</tags>` : ''}
          ${post.data.category ? `<category>${post.data.category}</category>` : ''}
          ${post.data.timelineYear ? `<timelineYear>${post.data.timelineYear}</timelineYear>` : ''}
          ${post.data.timelineEra ? `<timelineEra>${post.data.timelineEra}</timelineEra>` : ''}
          ${post.data.isKeyEvent !== undefined ? `<isKeyEvent>${post.data.isKeyEvent}</isKeyEvent>` : ''}
          ${post.data.image ? `<image>${post.data.image}</image>` : ''}
        </frontmatter>
      `,
      }
    }),
    customData: `<language>${siteConfig.lang}</language>`,
  })

  // Add CORS headers to the response
  return createCORSResponse(response)
}
