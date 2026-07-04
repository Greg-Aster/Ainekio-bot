// Type definitions for About page configuration

// Team section configuration
export interface TeamSectionConfig {
  enabled: boolean;
  title: string;
  description: string;
  layout: "grid" | "list" | "cards";
  columns: {
    mobile: number;
    tablet: number;
    desktop: number;
  };
  showEmail: boolean;
  showRole: boolean;
  avatarShape: "square" | "rounded" | "circle";
}

// Dynamic content section configuration
export interface ContentSectionConfig {
  enabled: boolean;
  defaultTitle: string;
  showTableOfContents: boolean;
}

// Contact section configuration
export interface ContactSectionConfig {
  enabled: boolean;
  title: string;
  description: string;
  contactInfo: {
    email: string;
    phone?: string;
    address?: string;
    hours?: string;
  };
  displayOrder: string[];
}

// Complete about page configuration
export interface AboutConfig {
  team: TeamSectionConfig;
  content: ContentSectionConfig;
  contact: ContactSectionConfig;
}

// Default about configuration
export const defaultAboutConfig: AboutConfig = {
  team: {
    enabled: true,
    title: "Our Team",
    description: "Meet the people behind the project",
    layout: "grid",
    columns: {
      mobile: 1,
      tablet: 2,
      desktop: 3
    },
    showEmail: true,
    showRole: true,
    avatarShape: "rounded"
  },
  content: {
    enabled: true,
    defaultTitle: "About The Project",
    showTableOfContents: true
  },
  contact: {
    enabled: true,
    title: "Get In Touch",
    description: "Have questions, ideas, or want to collaborate? We'd love to hear from you!",
    contactInfo: {
      email: "contact@example.com"
    },
    displayOrder: ["description", "email"]
  }
};
