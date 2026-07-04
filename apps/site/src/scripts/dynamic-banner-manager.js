// Enhanced BannerManager with support for in-page dynamic updates
// Add this to your client-side JavaScript, ideally in a separate file

class BannerManager {
    constructor() {
      this.currentType = null;
      this.rotationTimer = null;
      this.rotationIndex = 0;
      this.initialized = false;
      this.pendingUpdate = false;
    }

    getBannerWrapper() {
      return document.getElementById('dynamic-banner-wrapper') ||
        document.getElementById('banner-wrapper');
    }
  
    init() {
      if (this.initialized && !this.pendingUpdate) return;
      
      // Get the current banner type from the wrapper
      const bannerWrapper = this.getBannerWrapper();
      if (!bannerWrapper) return;
      
      this.currentType = bannerWrapper.dataset.bannerType || 'default';
      this.setupBanner();
      this.initialized = true;
      this.pendingUpdate = false;
  
      // Setup event listeners if not already set
      if (!this.listenersInitialized) {
        // Listen for Swup page transitions
        document.addEventListener('swup:contentReplaced', () => {
          // Allow a short delay for the new DOM to fully render
          setTimeout(() => this.handlePageTransition(), 50);
        });
        
        // Listen for custom banner update events
        document.addEventListener('banner:update', () => {
          this.pendingUpdate = true;
          setTimeout(() => this.init(), 50);
        });
        
        this.listenersInitialized = true;
      }
    }
  
    setupBanner() {
      // Clear any existing timers
      if (this.rotationTimer) {
        clearInterval(this.rotationTimer);
        this.rotationTimer = null;
      }
  
      // Handle specific banner types
      switch (this.currentType) {
        case 'rotating':
          this.setupRotatingBanner();
          break;
        case 'video':
          this.setupVideoBanner();
          break;
        case 'timeline':
          this.setupTimelineBanner();
          break;
      }
      
      // Set appropriate banner height
      this.updateBannerHeight();
    }
    
    updateBannerHeight() {
      const bannerWrapper = this.getBannerWrapper();
      if (!bannerWrapper) return;
      
      // Reset any inline styles
      bannerWrapper.style.height = '';
      
      // Set height based on banner type
      switch (this.currentType) {
        case 'video':
          bannerWrapper.style.height = '65vh';
          break;
        case 'timeline':
          bannerWrapper.style.height = '25vh';
          break;
        // Default and rotating use the CSS variables defined in the stylesheet
      }
    }
  
    setupRotatingBanner() {
      const rotatingBanner = document.getElementById('rotating-banner');
      if (!rotatingBanner) return;
      
      const images = rotatingBanner.querySelectorAll('img');
      if (images.length <= 1) return;
      
      // Set initial state
      this.rotationIndex = 0;
      images.forEach((img, index) => {
        img.classList.toggle('opacity-0', index !== 0);
        img.classList.toggle('opacity-100', index === 0);
      });
      
      // Start rotation
      this.rotationTimer = setInterval(() => {
        const prevIndex = this.rotationIndex;
        this.rotationIndex = (this.rotationIndex + 1) % images.length;
        
        // Fade out previous image
        images[prevIndex].classList.remove('opacity-100');
        images[prevIndex].classList.add('opacity-0');
        
        // Fade in next image
        images[this.rotationIndex].classList.remove('opacity-0');
        images[this.rotationIndex].classList.add('opacity-100');
      }, 5000); // Change image every 5 seconds
    }
  
    setupVideoBanner() {
      const videoBanner = document.getElementById('video-banner');
      if (!videoBanner || videoBanner.dataset.initialized === 'true') return;
      
      const iframe = videoBanner.querySelector('iframe');
      if (!iframe) return;
      
      // Ensure video is properly loaded and playing
      const originalSrc = iframe.src;
      iframe.src = originalSrc + (originalSrc.includes('?') ? '&' : '?') + '_t=' + Date.now();
      videoBanner.dataset.initialized = 'true';
    }
  
    setupTimelineBanner() {
      // Initialize timeline behavior if needed
      const timelineBanner = document.getElementById('timeline-banner');
      if (!timelineBanner) return;
      
      // Add any timeline-specific initialization here
      // For example, scroll to the centered position
      timelineBanner.querySelector('.timeline-container')?.scrollTo({
        left: (timelineBanner.querySelector('.timeline-container')?.scrollWidth || 0) / 4,
        behavior: 'smooth'
      });
    }
  
    handlePageTransition() {
      // Get the possibly new banner type
      const bannerWrapper = this.getBannerWrapper();
      if (!bannerWrapper) return;
      
      const newType = bannerWrapper.dataset.bannerType || 'default';
      
      // If banner type changed, update and reinitialize
      if (newType !== this.currentType) {
        this.currentType = newType;
        this.pendingUpdate = true;
        this.init();
      } else {
        // Even if type is the same, we might need to reinitialize
        // for example if we navigate between two pages with rotating banners
        this.setupBanner();
      }
    }
    
    // Add support for manually updating the banner (for in-page changes)
    updateBanner(type, content) {
      const bannerWrapper = this.getBannerWrapper();
      if (!bannerWrapper) return;
      
      // Update the banner type
      bannerWrapper.dataset.bannerType = type;
      this.currentType = type;
      
      // If content is provided, replace the banner content
      if (content) {
        bannerWrapper.innerHTML = content;
      }
      
      // Mark for update and reinitialize
      this.pendingUpdate = true;
      this.init();
    }
  }
  
  // Initialize banner manager
  const bannerManager = new BannerManager();
  
  // Run on initial page load
  document.addEventListener('DOMContentLoaded', () => {
    bannerManager.init();
  });
  
  // If the document is already loaded (which can happen with Swup)
  if (document.readyState === 'complete' || document.readyState === 'interactive') {
    setTimeout(() => bannerManager.init(), 100);
  }
  
  // Make banner manager globally accessible for scripts embedded in MDX
  window.bannerManager = bannerManager;
