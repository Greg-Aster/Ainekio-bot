// Create a function that will be called whenever we need to refresh a video
function refreshVideoBanner() {
    console.log("Attempting to refresh video banner...");
    const videoBanner = document.getElementById('video-banner');
    
    if (videoBanner) {
      console.log("Found video banner, refreshing iframe...");
      const iframe = videoBanner.querySelector('iframe');
      
      if (iframe) {
        // Store the original source
        const originalSrc = iframe.src;
        console.log("Original iframe src:", originalSrc);
        
        // Force reload by temporarily removing and then adding back the iframe
        const parentElement = iframe.parentElement;
        if (parentElement) {
          // Create a new iframe with the same properties
          const newIframe = document.createElement('iframe');
          newIframe.width = iframe.width;
          newIframe.height = iframe.height;
          newIframe.src = originalSrc;
          newIframe.frameBorder = iframe.frameBorder;
          newIframe.allow = iframe.allow;
          newIframe.allowFullscreen = iframe.allowFullscreen;
          newIframe.className = iframe.className;
          
          // Replace the old iframe with the new one
          parentElement.removeChild(iframe);
          parentElement.appendChild(newIframe);
          console.log("Iframe replaced successfully");
        }
      }
    }
  }
  
  // Set up a MutationObserver to watch for changes to the DOM
  function setupVideoObserver() {
    console.log("Setting up video observer");
    
    // Create an observer instance
    const observer = new MutationObserver((mutations) => {
      mutations.forEach((mutation) => {
        // Check if any nodes were added
        if (mutation.addedNodes.length) {
          // Check each added node to see if it contains the video banner
          mutation.addedNodes.forEach((node) => {
            // If the node is an Element and has the right ID, or contains elements with the right ID
            if (node instanceof Element) {
              if (node.id === 'video-banner' || node.querySelector('#video-banner')) {
                console.log("Video banner detected in DOM changes");
                // Wait a moment for everything to settle, then refresh
                setTimeout(refreshVideoBanner, 100);
              }
            }
          });
        }
      });
    });
    
    // Start observing the document body for DOM changes
    observer.observe(document.body, { 
      childList: true, 
      subtree: true 
    });
    
    console.log("Observer started");
    
    // Also handle Swup events directly
    document.addEventListener('swup:contentReplaced', () => {
      console.log("Swup content replaced event detected");
      setTimeout(refreshVideoBanner, 200);
    });
  }
  
  // Initialize everything once the DOM is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', setupVideoObserver);
  } else {
    // DOM is already ready
    setupVideoObserver();
  }
  
  // Also try immediately in case the DOM is already loaded and we missed events
  setTimeout(refreshVideoBanner, 100);