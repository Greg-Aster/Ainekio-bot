import type { APIRoute } from 'astro'

export const GET: APIRoute = () =>
  new Response(null, {
    status: 301,
    headers: {
      Location: new URL('/sitemap-index.xml', import.meta.env.SITE).href,
    },
  })
