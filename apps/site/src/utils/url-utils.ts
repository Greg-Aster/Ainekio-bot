import i18nKey from '@i18n/i18nKey'
import { i18n } from '@i18n/translation'
import {
  getCategoryUrl as getSharedCategoryUrl,
  getDir as getSharedDir,
  getPostUrlBySlug as getSharedPostUrlBySlug,
  getTagUrl as getSharedTagUrl,
  pathsEqual as pathsEqualShared,
  url as sharedUrl,
} from '@ainekio/blog-core/utils'

export function pathsEqual(path1: string, path2: string): boolean {
  return pathsEqualShared(path1, path2)
}

export function getPostUrlBySlug(slug: string): string {
  return getSharedPostUrlBySlug(slug, import.meta.env.BASE_URL)
}

export function getCategoryUrl(category: string): string {
  return getSharedCategoryUrl(
    category,
    i18n(i18nKey.uncategorized),
    import.meta.env.BASE_URL,
  )
}

export function getTagUrl(tag: string): string {
  return getSharedTagUrl(tag, import.meta.env.BASE_URL)
}

export function getDir(path: string): string {
  return getSharedDir(path)
}

export function url(path: string): string {
  return sharedUrl(path, import.meta.env.BASE_URL)
}
