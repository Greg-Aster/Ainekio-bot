// src/utils/starUtils.ts
// Shared utilities between StarMapView and StarNode components

declare global {
  interface Window {
    THREE?: unknown
  }
}

export const ERA_COLORS = {
  'ancient-epoch': '#3b82f6',
  'awakening-era': '#8b5cf6',
  'golden-age': '#6366f1',
  'conflict-epoch': '#ec4899',
  'singularity-conflict': '#ef4444',
  'transcendent-age': '#14b8a6',
  'final-epoch': '#22c55e',
  unknown: '#6366f1',
} as const

export const COLOR_SPECTRUM = [
  '#ef4444',
  '#f43f5e',
  '#f97316',
  '#f59e0b',
  '#eab308',
  '#facc15',
  '#22c55e',
  '#10b981',
  '#14b8a6',
  '#06b6d4',
  '#0ea5e9',
  '#3b82f6',
  '#6366f1',
  '#8b5cf6',
  '#a855f7',
  '#d946ef',
  '#ec4899',
] as const

export const STAR_TYPES = [
  'point',
  'classic',
  'sparkle',
  'refraction',
  'halo',
  'subtle',
] as const

/**
 * Simple hash function for consistent randomization
 */
export function hashCode(str: string): number {
  if (!str) return 0
  return Math.abs(
    str.split('').reduce((a, b) => (a << 5) - a + b.charCodeAt(0), 0),
  )
}

/**
 * Get star color based on era or hash
 */
export function getStarColor(
  id: string,
  era?: string,
  useEraColors?: boolean,
): string {
  if (useEraColors && era && ERA_COLORS[era as keyof typeof ERA_COLORS]) {
    return ERA_COLORS[era as keyof typeof ERA_COLORS]
  }
  const hash = hashCode(id)
  return COLOR_SPECTRUM[hash % COLOR_SPECTRUM.length]
}

/**
 * Get star type based on hash and importance
 */
export function getStarType(id: string, isKeyEvent: boolean): string {
  const hash = hashCode(id)
  if (isKeyEvent) {
    return ['classic', 'sparkle', 'refraction', 'halo'][hash % 4]
  }
  return STAR_TYPES[hash % STAR_TYPES.length]
}

/**
 * Get size factor with variation
 */
export function getSizeFactor(isKeyEvent: boolean): number {
  return isKeyEvent ? 1.2 : 0.85 + Math.random() * 0.3
}

/**
 * Get animation duration based on hash
 */
export function getAnimationDuration(id: string): number {
  const hash = hashCode(id)
  return 4 + (hash % 5)
}

/**
 * Constellation configurations for 3D positioning
 */
export const CONSTELLATION_CONFIG = {
  'ancient-epoch': { center: [0, 45], spread: 40, pattern: 'ancient_wisdom' },
  'awakening-era': { center: [60, 50], spread: 35, pattern: 'rising_dawn' },
  'golden-age': { center: [120, 55], spread: 45, pattern: 'crown' },
  'conflict-epoch': {
    center: [180, 40],
    spread: 40,
    pattern: 'crossed_swords',
  },
  'singularity-conflict': {
    center: [240, 45],
    spread: 35,
    pattern: 'supernova',
  },
  'transcendent-age': { center: [300, 60], spread: 40, pattern: 'ascension' },
  'final-epoch': { center: [340, 65], spread: 30, pattern: 'omega' },
  unknown: { center: [30, 35], spread: 25, pattern: 'scattered' },
} as const

/**
 * Simple canvas star texture generator
 */
export function createSimpleStarTexture(
  color: string,
  isKeyEvent = false,
  size = 64,
): HTMLCanvasElement {
  const canvas = document.createElement('canvas')
  canvas.width = canvas.height = size
  const ctx = canvas.getContext('2d')!

  const center = size / 2
  const radius = isKeyEvent ? 8 : 5

  // Outer glow
  const gradient = ctx.createRadialGradient(
    center,
    center,
    0,
    center,
    center,
    radius * 3,
  )
  gradient.addColorStop(0, color)
  gradient.addColorStop(0.5, color + '80')
  gradient.addColorStop(1, color + '00')

  ctx.fillStyle = gradient
  ctx.beginPath()
  ctx.arc(center, center, radius * 3, 0, Math.PI * 2)
  ctx.fill()

  // Core star
  ctx.fillStyle = color
  ctx.beginPath()
  ctx.arc(center, center, radius, 0, Math.PI * 2)
  ctx.fill()

  return canvas
}

/**
 * Device detection utilities
 */
export const deviceUtils = {
  isMobile: () =>
    /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(
      navigator.userAgent,
    ),
  isMobilePortrait: () =>
    deviceUtils.isMobile() &&
    window.matchMedia('(orientation: portrait)').matches,
  getTouchEventName: () => (deviceUtils.isMobile() ? 'touchend' : 'click'),
}

/**
 * Simplified card rendering with Tailwind classes
 */
export function createStarCard(eventData: any): string {
  return `
    <div class="bg-slate-800/90 backdrop-blur-sm rounded-lg shadow-lg p-3 text-white max-w-[280px]">
      <h3 class="font-bold text-sm mb-1 text-white">${eventData.title}</h3>
      <p class="text-xs text-gray-300 line-clamp-2 mb-2">${eventData.description || ''}</p>
      <a href="/posts/${eventData.slug}/#post-container" 
         class="text-xs bg-sky-600 hover:bg-sky-500 px-2 py-1 rounded text-white inline-block transition-colors">
        View Event →
      </a>
    </div>
  `
}

/**
 * Position card with smart placement
 */
export function positionCard(
  cardElement: HTMLElement,
  screenPosition: { x: number; y: number; isInFront: boolean },
) {
  if (!screenPosition.isInFront) {
    cardElement.className =
      'fixed opacity-0 pointer-events-none transition-opacity duration-300 z-[200]'
    return
  }

  const margin = 20
  const cardWidth = 280
  const cardHeight = 120

  let x = screenPosition.x + margin
  let y = screenPosition.y - cardHeight / 2

  // Keep card in viewport
  if (x + cardWidth > window.innerWidth - margin) {
    x = screenPosition.x - cardWidth - margin
  }
  if (y < margin) y = margin
  if (y + cardHeight > window.innerHeight - margin) {
    y = window.innerHeight - cardHeight - margin
  }

  cardElement.style.left = `${x}px`
  cardElement.style.top = `${y}px`
  cardElement.className =
    'fixed opacity-100 pointer-events-auto transition-opacity duration-300 z-[200]'
}

/**
 * Three.js script loader with promises (legacy - Threlte handles Three.js loading)
 */
export async function loadThreeJS(): Promise<boolean> {
  if (window.THREE) return true

  try {
    await loadScript(
      'https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js',
    )
    return !!window.THREE
  } catch (error) {
    console.error('Failed to load Three.js:', error)
    return false
  }
}

function loadScript(src: string): Promise<void> {
  return new Promise((resolve, reject) => {
    if (document.querySelector(`script[src="${src}"]`)) return resolve()

    const script = document.createElement('script')
    script.src = src
    script.onload = () => resolve()
    script.onerror = reject
    document.head.appendChild(script)
  })
}

/**
 * Enhanced star texture generation for Three.js
 */
export function createEnhancedStarTexture(
  color: string,
  starType: string,
  isKeyEvent = false,
  size = 256,
): HTMLCanvasElement {
  const canvas = document.createElement('canvas')
  canvas.width = canvas.height = size
  const ctx = canvas.getContext('2d')!

  const center = size / 2
  const baseRadius = isKeyEvent ? size * 0.04 : size * 0.03
  const sizeFactor = getSizeFactor(isKeyEvent)
  const finalRadius = baseRadius * sizeFactor

  // Clear canvas
  ctx.clearRect(0, 0, size, size)

  // Enhanced multi-layer glow
  const glowLayers = [
    { radius: finalRadius * 15, opacity: 0.04, blur: 25 },
    { radius: finalRadius * 10, opacity: 0.08, blur: 20 },
    { radius: finalRadius * 6, opacity: 0.15, blur: 15 },
    { radius: finalRadius * 3, opacity: 0.25, blur: 8 },
  ]

  glowLayers.forEach(layer => {
    ctx.save()
    ctx.filter = `blur(${layer.blur}px)`

    const gradient = ctx.createRadialGradient(
      center,
      center,
      0,
      center,
      center,
      layer.radius,
    )
    const alpha = Math.floor(layer.opacity * 255)
      .toString(16)
      .padStart(2, '0')
    gradient.addColorStop(0, color + alpha)
    gradient.addColorStop(
      0.5,
      color +
        Math.floor(layer.opacity * 150)
          .toString(16)
          .padStart(2, '0'),
    )
    gradient.addColorStop(1, color + '00')

    ctx.fillStyle = gradient
    ctx.beginPath()
    ctx.arc(center, center, layer.radius, 0, Math.PI * 2)
    ctx.fill()
    ctx.restore()
  })

  // Main star shape
  ctx.save()
  ctx.globalCompositeOperation = 'source-over'

  switch (starType) {
    case 'point':
      ctx.fillStyle = color
      ctx.beginPath()
      ctx.arc(center, center, finalRadius * 1.2, 0, Math.PI * 2)
      ctx.fill()
      break

    case 'classic':
      drawStar(ctx, center, center, 5, finalRadius * 2, finalRadius * 1, color)
      break

    case 'sparkle':
      drawStar(
        ctx,
        center,
        center,
        4,
        finalRadius * 1.8,
        finalRadius * 0.8,
        color,
      )
      // Add cross lines
      ctx.strokeStyle = color + 'AA'
      ctx.lineWidth = 2
      ctx.beginPath()
      ctx.moveTo(center - finalRadius * 3, center)
      ctx.lineTo(center + finalRadius * 3, center)
      ctx.moveTo(center, center - finalRadius * 3)
      ctx.lineTo(center, center + finalRadius * 3)
      ctx.stroke()
      break

    case 'refraction':
      // Central core
      ctx.fillStyle = color
      ctx.beginPath()
      ctx.arc(center, center, finalRadius * 1.2, 0, Math.PI * 2)
      ctx.fill()

      // Refraction lines
      ctx.strokeStyle = color + '80'
      ctx.lineWidth = 2
      ctx.beginPath()
      ctx.moveTo(center - finalRadius * 4, center)
      ctx.lineTo(center + finalRadius * 4, center)
      ctx.moveTo(center, center - finalRadius * 4)
      ctx.lineTo(center, center + finalRadius * 4)
      ctx.stroke()
      break

    case 'halo':
      // Multiple halos
      const haloRings = [
        { radius: finalRadius * 1.2, opacity: 1 },
        { radius: finalRadius * 2, opacity: 0.6 },
        { radius: finalRadius * 2.8, opacity: 0.3 },
      ]

      haloRings.forEach(ring => {
        ctx.fillStyle =
          color +
          Math.floor(ring.opacity * 255)
            .toString(16)
            .padStart(2, '0')
        ctx.beginPath()
        ctx.arc(center, center, ring.radius, 0, Math.PI * 2)
        ctx.fill()
      })
      break

    default: // subtle
      ctx.fillStyle = color
      ctx.beginPath()
      ctx.arc(center, center, finalRadius * 1.1, 0, Math.PI * 2)
      ctx.fill()

      ctx.strokeStyle = color + '99'
      ctx.lineWidth = 1
      ctx.beginPath()
      ctx.moveTo(center - finalRadius * 2.5, center)
      ctx.lineTo(center + finalRadius * 2.5, center)
      ctx.moveTo(center, center - finalRadius * 2.5)
      ctx.lineTo(center, center + finalRadius * 2.5)
      ctx.stroke()
      break
  }

  ctx.restore()
  return canvas
}

/**
 * Helper function to draw star shapes
 */
function drawStar(
  ctx: CanvasRenderingContext2D,
  cx: number,
  cy: number,
  spikes: number,
  outerRadius: number,
  innerRadius: number,
  color: string,
) {
  let rot = (Math.PI / 2) * 3
  let x = cx
  let y = cy
  const step = Math.PI / spikes

  ctx.beginPath()
  ctx.moveTo(cx, cy - outerRadius)

  for (let i = 0; i < spikes; i++) {
    x = cx + Math.cos(rot) * outerRadius
    y = cy + Math.sin(rot) * outerRadius
    ctx.lineTo(x, y)
    rot += step

    x = cx + Math.cos(rot) * innerRadius
    y = cy + Math.sin(rot) * innerRadius
    ctx.lineTo(x, y)
    rot += step
  }

  ctx.lineTo(cx, cy - outerRadius)
  ctx.closePath()
  ctx.fillStyle = color
  ctx.fill()
}
