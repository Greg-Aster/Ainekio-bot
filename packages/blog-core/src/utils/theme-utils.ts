import type { LIGHT_DARK_MODE } from '../types'
import { AUTO_MODE, DARK_MODE, LIGHT_MODE } from '../constants'

export function getDefaultHue(fallback = 250): number {
  if (typeof document === 'undefined') return fallback
  const configCarrier = document.getElementById('config-carrier')
  return Number.parseInt(configCarrier?.dataset.hue || String(fallback))
}

export function getHue(): number {
  if (typeof localStorage === 'undefined') return getDefaultHue()
  const stored = localStorage.getItem('hue')
  return stored ? Number.parseInt(stored) : getDefaultHue()
}

export function setHue(hue: number): void {
  if (typeof localStorage === 'undefined') return
  localStorage.setItem('hue', String(hue))
  const r = document.querySelector(':root') as HTMLElement
  if (!r) return
  r.style.setProperty('--hue', String(hue))
}

export function applyThemeToDocument(theme: LIGHT_DARK_MODE): void {
  if (typeof document === 'undefined') return

  switch (theme) {
    case LIGHT_MODE:
      document.documentElement.classList.remove('dark')
      break
    case DARK_MODE:
      document.documentElement.classList.add('dark')
      break
    case AUTO_MODE:
      if (window.matchMedia('(prefers-color-scheme: dark)').matches) {
        document.documentElement.classList.add('dark')
      } else {
        document.documentElement.classList.remove('dark')
      }
      break
  }
}

export function setTheme(theme: LIGHT_DARK_MODE): void {
  if (typeof localStorage === 'undefined') return
  localStorage.setItem('theme', theme)
  applyThemeToDocument(theme)
}

export function getStoredTheme(defaultTheme: LIGHT_DARK_MODE): LIGHT_DARK_MODE {
  if (typeof localStorage === 'undefined') return defaultTheme
  const stored = localStorage.getItem('theme') as LIGHT_DARK_MODE
  return stored || defaultTheme
}
