// Import types
import type {
  CommunityConfig,
  ContactConfig,
  DiscordConfig,
  EventsConfig,
  GuidelinesConfig,
  HeroConfig,
  NewsletterConfig,
} from '../types/communityconfig'

// Community page configuration
export const communityConfig: CommunityConfig = {
  hero: {
    title: 'Join Our Community',
    description:
      'Connect with other members, share ideas, get help, and stay updated on the latest developments.',
    showGraphic: true,
    options: [],
  },
  discord: {
    enabled: true,
    title: 'Discord Community',
    description: '',
    inviteUrl: '',
    buttonText: '',
    features: [],
    channels: [],
  },
  contact: {
    enabled: true,
    title: 'Get in Touch',
    description: '',
    formActionUrl: '',
    buttonText: '',
    features: [],
    formFields: {
      name: { label: 'Name', placeholder: 'Your name', required: true },
      email: { label: 'Email', placeholder: 'your@email.com', required: true },
      subject: {
        label: 'Subject',
        placeholder: 'Message subject',
        required: true,
      },
      message: {
        label: 'Message',
        placeholder: 'Your message...',
        required: true,
        rows: 5,
      },
    },
  },
  newsletter: {
    enabled: false,
    title: 'Newsletter',
    description: '',
    buttonText: '',
    features: [],
    consentText: '',
  },
  events: {
    enabled: false,
    title: 'Events',
    description: '',
    calendarButtonText: '',
    calendarUrl: '',
  },
  guidelines: {
    enabled: true,
    title: 'Community Guidelines',
    description: '',
    items: [],
  },
}
