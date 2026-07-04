export function pathsEqual(path1: string, path2: string): boolean {
  const normalizedPath1 = path1.replace(/^\/|\/$/g, '').toLowerCase()
  const normalizedPath2 = path2.replace(/^\/|\/$/g, '').toLowerCase()
  return normalizedPath1 === normalizedPath2
}

export function joinUrl(...parts: string[]): string {
  const joined = parts.join('/')
  return joined.replace(/\/+/g, '/')
}

export function getPostUrlBySlug(slug: string, baseUrl = ''): string {
  return joinUrl(baseUrl, `/posts/${slug}/`)
}

export function getCategoryUrl(
  category: string,
  uncategorizedLabel: string,
  baseUrl = ''
): string {
  if (category === uncategorizedLabel) {
    return joinUrl(baseUrl, '/archive/category/uncategorized/')
  }
  return joinUrl(baseUrl, `/archive/category/${category.toLowerCase()}/`)
}

export function getTagUrl(tag: string, baseUrl = ''): string {
  return joinUrl(baseUrl, `/archive/tag/${tag.toLowerCase()}/`)
}

export function getDir(path: string): string {
  const lastSlashIndex = path.lastIndexOf('/')
  if (lastSlashIndex < 0) {
    return '/'
  }
  return path.substring(0, lastSlashIndex + 1)
}

export function url(path: string, baseUrl = ''): string {
  return joinUrl('', baseUrl, path)
}
