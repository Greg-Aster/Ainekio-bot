// About page configuration

import type { AboutConfig } from '../types/aboutconfig';
import { defaultAboutConfig } from '../types/aboutconfig';

// Export the about page configuration
export const aboutConfig: AboutConfig = {
  ...defaultAboutConfig,
  // Match the original about.astro layout
  team: {
    ...defaultAboutConfig.team,
    enabled: true,
    title: "Our Team",
    description: "", // The original didn't have a description
    layout: "grid",
    columns: {
      mobile: 1,
      tablet: 2,
      desktop: 3
    },
    showEmail: true,
    showRole: true,
    avatarShape: "rounded" // Match the original rounded-lg
  },
  content: {
    ...defaultAboutConfig.content,
    enabled: true,
    defaultTitle: "About The Project",
    showTableOfContents: true // The original had TOC imported
  },
  contact: {
    ...defaultAboutConfig.contact,
    enabled: true,
    title: "Get In Touch",
    description: "Have questions, ideas, or want to collaborate? We'd love to hear from you! Please Email", // Match original text
    contactInfo: {
      email: "Greg@dndiy.org" // Match the original email
    },
    displayOrder: ["description", "email"] // Match the original order
  }
};