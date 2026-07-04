// src/utils/friend-posts-utils.ts
// Simple utility to get friend posts in a format compatible with PostCard.astro

import {
  getFriendPostsAsEntries,
  isFriendContentEnabled,
} from '../stores/friendStore'

type FormattedFriendPost = {
  id: string
  slug: string
  data: {
    title: string
    published: Date
    updated: Date | undefined
    tags: string[]
    category: string
    image: string | undefined
    description: string
    isFriendPost: boolean
    friendName: string | undefined
    friendUrl: string | undefined
    friendAvatar: string | undefined
    url: string
  }
  render: () => {
    remarkPluginFrontmatter: { words: number; minutes: number; excerpt: string }
  }
}

// Check if friend content should be shown
export function shouldShowFriendContent(): boolean {
  // Only works in browser
  if (typeof window === 'undefined' || typeof localStorage === 'undefined') {
    return false
  }

  const isAuthenticated = localStorage.getItem('isAuthenticated') === 'true'
  const expiresAt = Number(localStorage.getItem('authExpiresAt') || '0')

  if (!isAuthenticated || !expiresAt || Date.now() >= expiresAt) {
    localStorage.removeItem('isAuthenticated')
    localStorage.removeItem('authExpiresAt')
    return false
  }

  return isFriendContentEnabled()
}

// Get friend posts formatted to be compatible with PostCard.astro
export function getFormattedFriendPosts(): FormattedFriendPost[] {
  // Get raw friend posts
  const friendEntries = getFriendPostsAsEntries()

  // Format for PostCard.astro
  return friendEntries.map(entry => ({
    id: entry.id,
    slug: entry.slug,
    data: {
      title: entry.data.title,
      published: entry.data.published,
      updated: entry.data.updated,
      tags: entry.data.tags || [],
      category: entry.data.category || '',
      image: entry.data.image,
      description: entry.data.description,
      isFriendPost: true,
      friendName: entry.data.friendName ?? undefined,
      friendUrl: entry.data.friendUrl ?? undefined,
      friendAvatar: entry.data.friendAvatar ?? undefined,
      url: entry.data.sourceUrl || `/friend/${entry.slug}`,
    },
    render: () => entry.render(),
  }))
}
