// Community page configuration types

// Discord section configuration
export interface DiscordConfig {
  enabled: boolean;
  title: string;
  description: string;
  inviteUrl: string;
  buttonText: string;
  features: {
    title: string;
    description: string;
    icon: string;
  }[];
  channels: {
    name: string;
    description: string;
    color: string;
  }[];
}

// Contact section configuration
export interface ContactConfig {
  enabled: boolean;
  title: string;
  description: string;
  formActionUrl: string;
  buttonText: string;
  features: {
    title: string;
    description: string;
    icon: string;
  }[];
  formFields: {
    name: {
      label: string;
      placeholder: string;
      required: boolean;
    };
    email: {
      label: string;
      placeholder: string;
      required: boolean;
    };
    subject: {
      label: string;
      placeholder: string;
      required: boolean;
    };
    message: {
      label: string;
      placeholder: string;
      required: boolean;
      rows: number;
    };
  };
}

// Newsletter section configuration
export interface NewsletterConfig {
  enabled: boolean;
  title: string;
  description: string;
  buttonText: string;
  features: {
    title: string;
    description: string;
    icon: string;
  }[];
  consentText: string;
}

// Events section configuration
export interface EventsConfig {
  enabled: boolean;
  title: string;
  description: string;
  calendarButtonText: string;
  calendarUrl: string;
}

// Guidelines section configuration
export interface GuidelinesConfig {
  enabled: boolean;
  title: string;
  description: string;
  items: string[];
}

// Hero section configuration
export interface HeroConfig {
  title: string;
  description: string;
  showGraphic: boolean;
  options: {
    title: string;
    description: string;
    icon: string;
    sectionId: string;
    enabled: boolean;
  }[];
}

// Complete community configuration
export interface CommunityConfig {
  hero: HeroConfig;
  discord: DiscordConfig;
  contact: ContactConfig;
  newsletter: NewsletterConfig;
  events: EventsConfig;
  guidelines: GuidelinesConfig;
}

// Default community configuration
export const defaultCommunityConfig: CommunityConfig = {
  hero: {
    title: "Join Our Community",
    description: "Connect with other members, share ideas, get help, and stay updated on the latest developments. Choose how you'd like to engage with our growing community.",
    showGraphic: false,
    options: [
      {
        title: "Discord Community",
        description: "Real-time chat & discussions",
        icon: "mdi:discord",
        sectionId: "discord-section",
        enabled: true
      },
      {
        title: "Email Newsletter",
        description: "Regular updates & announcements",
        icon: "famicons:mail",
        sectionId: "newsletter-section",
        enabled: false
      },
      {
        title: "Community Events",
        description: "Workshops, calls & meetups",
        icon: "mdi:calendar-outline",
        sectionId: "events-section",
        enabled: false
      },
      {
        title: "Direct Contact",
        description: "Send private messages & feedback",
        icon: "mdi:message-outline",
        sectionId: "contact-section",
        enabled: true
      }
    ]
  },
  discord: {
    enabled: true,
    title: "Discord Community",
    description: "Our Discord server is the heart of our real-time community. Connect with other members, share ideas, get help, and stay updated on the latest developments.",
    inviteUrl: "https://discord.gg/je7Vyw75tR",
    buttonText: "Join Our Discord Server",
    features: [
      {
        title: "Active Discussions",
        description: "Engage in conversations about projects, ideas, and techniques",
        icon: "mdi:chat-processing-outline"
      },
      {
        title: "Community Support",
        description: "Get help from experienced members and contribute your knowledge",
        icon: "mdi:help-circle-outline"
      },
      {
        title: "Stay Updated",
        description: "Receive announcements and updates about new developments",
        icon: "mdi:bell-outline"
      }
    ],
    channels: [
      {
        name: "#general",
        description: "Main discussions",
        color: "blue-500"
      }
    ]
  },
  contact: {
    enabled: true,
    title: "Get in Touch",
    description: "Have a question, suggestion, or feedback? Reach out directly to our team. We're here to help and would love to hear from you.",
    formActionUrl: "https://formspree.io/f/xwpvzlgy",
    buttonText: "Send Message",
    features: [
      {
        title: "Questions & Support",
        description: "Get help with any issues or questions you might have",
        icon: "mdi:frequently-asked-questions"
      },
      {
        title: "Suggestions & Ideas",
        description: "Share your thoughts on how we can improve",
        icon: "mdi:lightbulb-on-outline"
      },
      {
        title: "Collaboration Opportunities",
        description: "Discuss potential partnerships or collaborative projects",
        icon: "mdi:handshake-outline"
      }
    ],
    formFields: {
      name: {
        label: "Your Name",
        placeholder: "John Doe",
        required: true
      },
      email: {
        label: "Email Address",
        placeholder: "your@email.com",
        required: true
      },
      subject: {
        label: "Subject",
        placeholder: "Question about...",
        required: true
      },
      message: {
        label: "Your Message",
        placeholder: "Type your message here...",
        required: true,
        rows: 4
      }
    }
  },
  newsletter: {
    enabled: false,
    title: "Email Newsletter",
    description: "Subscribe to our newsletter to receive regular updates, tutorials, and announcements directly to your inbox. Stay informed without the noise.",
    buttonText: "Subscribe Now",
    features: [
      {
        title: "Weekly Digest",
        description: "Summary of important updates and community highlights",
        icon: "mdi:newspaper-variant-outline"
      },
      {
        title: "Event Notifications",
        description: "Early announcements about upcoming workshops and meetups",
        icon: "mdi:calendar-check-outline"
      },
      {
        title: "Exclusive Content",
        description: "Special guides and resources available only to subscribers",
        icon: "mdi:star-outline"
      }
    ],
    consentText: "I agree to receive email newsletters and understand I can unsubscribe at any time."
  },
  events: {
    enabled: false,
    title: "Community Events",
    description: "Join our regular community events to learn, share, and connect with other members. From workshops to casual meetups, there's something for everyone.",
    calendarButtonText: "View Full Event Calendar",
    calendarUrl: "#"
  },
  guidelines: {
    enabled: true,
    title: "Community Guidelines",
    description: "To ensure our community remains a positive and productive space, we ask all members to follow these basic guidelines:",
    items: [
      "Be respectful and kind to other community members",
      "Keep discussions relevant to the appropriate channels",
      "Share knowledge freely and help others when you can",
      "No spam, excessive self-promotion, or disruptive behavior",
      "Respect privacy and confidentiality of others"
    ]
  }
};
