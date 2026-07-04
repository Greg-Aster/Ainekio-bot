import { getCollection } from 'astro:content'
import { profileConfig, siteConfig } from '../config/config'

export async function GET(): Promise<Response> {
  console.log('Friend content JSON endpoint called')

  try {
    // Get published posts
    const posts = await getCollection('posts', post => !post.data.draft)

    // Sort by published date, newest first
    const sortedPosts = posts.sort(
      (a, b) =>
        new Date(b.data.published).getTime() -
        new Date(a.data.published).getTime(),
    )

    // Include all posts, not just the most recent 10
    const allPosts = sortedPosts

    // Format posts for the API - only including frontmatter data
    const formattedPosts = allPosts.map(post => {
      return {
        id: post.id,
        title: post.data.title,
        slug: post.slug,
        description: post.data.description || '',
        published: post.data.published.toISOString(),
        updated: post.data.updated ? post.data.updated.toISOString() : null,
        tags: post.data.tags || [],
        category: post.data.category || '',
        image: post.data.image || null,
      }
    })

    console.log(
      `Exposing ${formattedPosts.length} posts via friend-content.json`,
    )

    // Create the friend content JSON structure
    const friendContent = {
      site: {
        name: siteConfig.title,
        description: siteConfig.description,
        url: siteConfig.url || import.meta.env.SITE || '',
        owner: profileConfig.name,
        avatar: profileConfig.avatar || '/avatar.png',
      },
      cors: true,
      version: '1.0',
      generated: new Date().toISOString(),
      posts: formattedPosts,
    }

    // Return the JSON response with proper CORS headers
    return new Response(JSON.stringify(friendContent), {
      status: 200,
      headers: {
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Methods': 'GET, HEAD, OPTIONS',
        'Access-Control-Allow-Headers': 'Content-Type, Accept',
        'Cache-Control': 'max-age=3600',
      },
    })
  } catch (error) {
    console.error('Error generating friend content JSON:', error)
    const message = error instanceof Error ? error.message : 'Unknown error'
    // Return a meaningful error response
    return new Response(
      JSON.stringify({
        error: 'Failed to generate friend content',
        message: message,
      }),
      {
        status: 500,
        headers: {
          'Content-Type': 'application/json',
          'Access-Control-Allow-Origin': '*',
        },
      },
    )
  }
}
