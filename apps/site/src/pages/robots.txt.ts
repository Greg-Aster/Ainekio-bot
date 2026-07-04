import type { APIRoute } from 'astro'

const robotsTxt = `
User-agent: *
Allow: /
Disallow: /configs/
Disallow: /new-post/
Disallow: /friends/

Sitemap: ${new URL('sitemap-index.xml', import.meta.env.SITE).href}
Sitemap: ${new URL('sitemap.xml', import.meta.env.SITE).href}
`.trim()

export const GET: APIRoute = () => {
  return new Response(robotsTxt, {
    headers: {
      'Content-Type': 'text/plain; charset=utf-8',
    },
  })
}
