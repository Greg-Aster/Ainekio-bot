export interface BannerAnimationConfig {
  enabled: boolean
  interval: number
  transitionDuration: number
  direction?: 'forward' | 'reverse' | 'alternate'
  randomStart?: boolean // true = pick a random image on each page load
}

export interface BannerItemPreviewDetails {
  hasValidLink?: boolean
  originalHref?: string
  urlForDisplay?: string
  previewTitle?: string
  previewDescription?: string
  previewIconSVG?: string
  isVideoButton?: boolean
}

export interface BannerControllerConfig {
  containerId: string
  animationConfig: BannerAnimationConfig
  getBannerItemPreviewDetails?: (index: number) => BannerItemPreviewDetails | null
  isVideoBannerItem?: (item: any) => boolean
  isImageBannerItem?: (item: any) => boolean
}

export enum VideoLoadingState {
  IDLE = 'idle',
  LOADING = 'loading',
  READY = 'ready',
  ERROR = 'error',
}

class BannerAnimationController {
  private config: BannerControllerConfig
  private container: HTMLElement | null = null
  private slides: HTMLElement[] = []
  private currentIndex = 0
  private timer: number | null = null

  constructor(config: BannerControllerConfig) {
    this.config = config
  }

  initialize(): boolean {
    this.container = document.getElementById(this.config.containerId)
    if (!this.container) return false

    this.slides = Array.from(
      this.container.querySelectorAll<HTMLElement>('.banner-slide'),
    )
    if (this.slides.length === 0) return false

    const startIndex = this.config.animationConfig.randomStart
      ? Math.floor(Math.random() * this.slides.length)
      : 0
    this.showSlide(startIndex)
    if (this.config.animationConfig.enabled && this.slides.length > 1) {
      this.start()
      this.container.addEventListener('mouseenter', () => this.pause())
      this.container.addEventListener('mouseleave', () => this.start())
      document.addEventListener('visibilitychange', () => {
        if (document.hidden) {
          this.pause()
        } else {
          this.start()
        }
      })
    }

    return true
  }

  private showSlide(index: number): void {
    this.slides.forEach((slide, i) => {
      slide.style.opacity = i === index ? '1' : '0'
    })
    this.currentIndex = index
  }

  private nextIndex(): number {
    const direction = this.config.animationConfig.direction ?? 'forward'
    if (direction === 'reverse') {
      return this.currentIndex === 0
        ? this.slides.length - 1
        : this.currentIndex - 1
    }
    return (this.currentIndex + 1) % this.slides.length
  }

  private tick = (): void => {
    this.showSlide(this.nextIndex())
  }

  start(): void {
    this.pause()
    const interval = Number(this.config.animationConfig.interval) || 5000
    this.timer = window.setInterval(this.tick, interval)
  }

  pause(): void {
    if (this.timer !== null) {
      window.clearInterval(this.timer)
      this.timer = null
    }
  }

  navigateToNext(): void {
    this.showSlide(this.nextIndex())
  }

  navigateToPrevious(): void {
    if (this.slides.length === 0) return
    const index =
      this.currentIndex === 0 ? this.slides.length - 1 : this.currentIndex - 1
    this.showSlide(index)
  }

  navigateToIndex(index: number): void {
    if (index < 0 || index >= this.slides.length) return
    this.showSlide(index)
  }

  destroy(): void {
    this.pause()
  }
}

export function createBannerAnimation(config: BannerControllerConfig) {
  return new BannerAnimationController(config)
}
