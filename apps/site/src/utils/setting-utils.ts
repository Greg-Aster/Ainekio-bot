import { siteConfig } from '@/config/config.ts'
import type { LIGHT_DARK_MODE } from '@/types/config'
import {
  applyThemeToDocument as applySharedThemeToDocument,
  getDefaultHue as getSharedDefaultHue,
  getHue as getSharedHue,
  getStoredTheme as getSharedStoredTheme,
  setHue as setSharedHue,
  setTheme as setSharedTheme,
} from '@ainekio/blog-core/utils'

export function getDefaultHue(): number {
  return getSharedDefaultHue(250)
}

export function getHue(): number {
  return getSharedHue()
}

export function setHue(hue: number): void {
  setSharedHue(hue)
}

export function applyThemeToDocument(theme: LIGHT_DARK_MODE): void {
  applySharedThemeToDocument(theme)
}

export function setTheme(theme: LIGHT_DARK_MODE): void {
  setSharedTheme(theme)
}

export function getStoredTheme(): LIGHT_DARK_MODE {
  return getSharedStoredTheme(siteConfig.defaultTheme)
}
