// Modified version with scroll-to-top
function handleCollapsibleClick(event) {
  const header = event.currentTarget;
  const content = header.nextElementSibling;
  const parentCard = header.closest('.card-base'); // Add this line
  
  if (content.hasAttribute('data-animating')) return;

  const isCurrentlyExpanded = content.style.maxHeight !== '0px' && content.style.maxHeight !== '';

  // Close all others
  document.querySelectorAll('.collapsible-content').forEach(otherContent => {
    if (otherContent !== content) {
      const otherHeader = otherContent.previousElementSibling;
      collapseSection(otherContent, otherHeader);
    }
  });

  // Toggle current with parentCard reference
  if (!isCurrentlyExpanded) {
    expandSection(content, header, parentCard); // Pass parentCard
  } else {
    collapseSection(content, header);
  }
}

// Modified expandSection to accept parentCard
function expandSection(content, header, parentCard) {
  const arrow = header.querySelector('.indicator-arrow');
  
  content.setAttribute('data-animating', 'true');
  content.style.maxHeight = '0px';
  content.style.opacity = '0';
  
  requestAnimationFrame(() => {
    const height = content.scrollHeight;
    
    content.style.maxHeight = `${height}px`;
    content.style.opacity = '1';
    
    header.setAttribute('aria-expanded', 'true');
    arrow?.classList.add('rotate-180');
    
    setTimeout(() => {
      content.removeAttribute('data-animating');
      // Add scroll logic here
      if (parentCard) {
        parentCard.scrollIntoView({
          behavior: 'smooth',
          block: 'start'
        });
      }
    }, 300); // Match animation duration
  });
}

// Keep collapseSection unchanged
function collapseSection(content, header) {
  const arrow = header.querySelector('.indicator-arrow');
  
  content.setAttribute('data-animating', 'true');
  content.style.maxHeight = '0px';
  content.style.opacity = '0';
  
  header.setAttribute('aria-expanded', 'false');
  arrow?.classList.remove('rotate-180');
  
  setTimeout(() => {
    content.removeAttribute('data-animating');
  }, 300);
}

// initCollapsibles remains unchanged
export function initCollapsibles() {
  const headers = document.querySelectorAll('.collapsible-header');
  
  if (headers.length === 0) {
    console.warn('No collapsible headers found to initialize');
    return;
  }
  
  headers.forEach(header => {
    header.removeEventListener('click', handleCollapsibleClick);
    header.addEventListener('click', handleCollapsibleClick);
    
    const content = header.nextElementSibling;
    
    if (content && content.classList.contains('collapsible-content')) {
      content.style.maxHeight = '0px';
      content.style.opacity = '0';
      header.setAttribute('aria-expanded', 'false');
    }
  });
  
  console.log(`Initialized ${headers.length} collapsible elements`);
}