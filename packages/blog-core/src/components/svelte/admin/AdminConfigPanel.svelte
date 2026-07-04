<script>
import { createEventDispatcher, onMount } from 'svelte'
import AboutConfigTab from './config-tabs/AboutConfigTab.svelte'
import AddonsConfigTab from './config-tabs/AddonsConfigTab.svelte'
import AdvancedConfigTab from './config-tabs/AdvancedConfigTab.svelte'
import AppearanceConfigTab from './config-tabs/AppearanceConfigTab.svelte'
import CommunityConfigTab from './config-tabs/CommunityConfigTab.svelte'
// config tabs
import GeneralConfigTab from './config-tabs/GeneralConfigTab.svelte'
import NavigationConfigTab from './config-tabs/NavigationConfigTab.svelte'
import ProfileConfigTab from './config-tabs/ProfileConfigTab.svelte'
import SecurityConfigTab from './config-tabs/SecurityConfigTab.svelte'
import TimelineConfigTab from './config-tabs/TimelineConfigTab.svelte'

import AboutConfigExporter from './AboutConfigExporter.svelte'
import BannerConfigExporter from './BannerConfigExporter.svelte'
import CommunityConfigExporter from './CommunityConfigExporter.svelte'
// exporters
import ConfigExporter from './ConfigExporter.svelte'
import GitHubIntegration from './GitHubIntegration.svelte'
import PostCardConfigExporter from './PostCardConfigExporter.svelte'

// Props for configuration objects
export let siteConfig
export let navBarConfig
export let profileConfig
export let licenseConfig
export let timelineConfig
export let avatarConfig
export let communityConfig
export let aboutConfig
export let postCardConfig
export let bannerConfig
export let addonsConfig

// State management
let activeTab = 'general'
const saveStatus = { saving: false, success: false, error: null }
let hasChanges = false

// Original config values for comparison
let originalConfigValues = {
  siteConfig: null,
  navBarConfig: null,
  profileConfig: null,
  licenseConfig: null,
  timelineConfig: null,
  avatarConfig: null,
  communityConfig: null,
  aboutConfig: null,
  postCardConfig: null,
  bannerConfig: null,
  addonsConfig: null,
}

// Event dispatcher for notifying parent components
const dispatch = createEventDispatcher()

// GitHub integration component reference
let githubIntegration

// Tabs configuration
const tabs = [
  { id: 'general', label: 'General', icon: 'mdi:cog-outline' },
  { id: 'navigation', label: 'Navigation', icon: 'mdi:navigation' },
  { id: 'profile', label: 'Profile', icon: 'mdi:account' },
  { id: 'appearance', label: 'Appearance', icon: 'mdi:palette-outline' },
  { id: 'timeline', label: 'Timeline', icon: 'mdi:timeline' },
  { id: 'community', label: 'Community', icon: 'mdi:account-group' },
  { id: 'about', label: 'About', icon: 'mdi:information-outline' },
  { id: 'security', label: 'Security', icon: 'mdi:shield-outline' },
  { id: 'advanced', label: 'Advanced', icon: 'mdi:code-json' },
  { id: 'addons', label: 'Add-ons', icon: 'mdi:puzzle-outline' },
]

// Tab switching
function setActiveTab(tabId) {
  activeTab = tabId
}

// State for config exporters
let showConfigExporter = false
let showCommunityConfigExporter = false
let showAboutConfigExporter = false
let showPostCardConfigExporter = false
let showBannerConfigExporter = false

// Function to handle saving all configuration
async function saveAllConfiguration() {
  try {
    saveStatus.saving = true
    saveStatus.error = null

    // Store in localStorage for demonstration/temporary savings
    localStorage.setItem('siteConfig', JSON.stringify(siteConfig))
    localStorage.setItem('navBarConfig', JSON.stringify(navBarConfig))
    localStorage.setItem('profileConfig', JSON.stringify(profileConfig))
    localStorage.setItem('licenseConfig', JSON.stringify(licenseConfig))
    localStorage.setItem('timelineConfig', JSON.stringify(timelineConfig))
    localStorage.setItem('avatarConfig', JSON.stringify(avatarConfig))
    localStorage.setItem('communityConfig', JSON.stringify(communityConfig))
    localStorage.setItem('aboutConfig', JSON.stringify(aboutConfig))
    localStorage.setItem('postCardConfig', JSON.stringify(postCardConfig))
    localStorage.setItem('bannerConfig', JSON.stringify(bannerConfig))
    localStorage.setItem('addonsConfig', JSON.stringify(addonsConfig))

    // Update original values to reflect saved state
    originalConfigValues = {
      siteConfig: JSON.stringify(siteConfig),
      navBarConfig: JSON.stringify(navBarConfig),
      profileConfig: JSON.stringify(profileConfig),
      licenseConfig: JSON.stringify(licenseConfig),
      timelineConfig: JSON.stringify(timelineConfig),
      avatarConfig: JSON.stringify(avatarConfig),
      communityConfig: JSON.stringify(communityConfig),
      aboutConfig: JSON.stringify(aboutConfig),
      postCardConfig: JSON.stringify(postCardConfig),
      bannerConfig: JSON.stringify(bannerConfig),
      addonsConfig: JSON.stringify(addonsConfig),
    }

    // Reset hasChanges flag
    hasChanges = false

    // Show success message
    saveStatus.success = true

    // Show the appropriate exporter based on active tab
    if (activeTab === 'community') {
      showCommunityConfigExporter = true
    } else if (activeTab === 'about') {
      showAboutConfigExporter = true
    } else if (activeTab === 'appearance') {
      // We want to offer the user the choice of which appearance config to export
      // If banner settings were modified, show banner exporter, otherwise show post card exporter
      const bannerChanged =
        JSON.stringify(bannerConfig) !== originalConfigValues.bannerConfig
      const postCardChanged =
        JSON.stringify(postCardConfig) !== originalConfigValues.postCardConfig

      if (bannerChanged) {
        showBannerConfigExporter = true
      } else {
        showPostCardConfigExporter = true
      }
    } else {
      showConfigExporter = true
    }

    // Notify parent component
    dispatch('saved', {
      siteConfig,
      navBarConfig,
      profileConfig,
      licenseConfig,
      timelineConfig,
      avatarConfig,
      communityConfig,
      aboutConfig,
      postCardConfig,
      bannerConfig,
    })

    // Reset success message after a delay
    setTimeout(() => {
      saveStatus.success = false
    }, 3000)
  } catch (error) {
    console.error('Error saving configuration:', error)
    saveStatus.error = 'Failed to save configuration. Please try again.'
  } finally {
    saveStatus.saving = false
  }
}

// Handle GitHub events
function handleGitHubConfigSaved(event) {
  const { success, error } = event.detail

  if (success) {
    // Update original values to reflect saved state
    originalConfigValues = {
      siteConfig: JSON.stringify(siteConfig),
      navBarConfig: JSON.stringify(navBarConfig),
      profileConfig: JSON.stringify(profileConfig),
      licenseConfig: JSON.stringify(licenseConfig),
      timelineConfig: JSON.stringify(timelineConfig),
      avatarConfig: JSON.stringify(avatarConfig),
      communityConfig: JSON.stringify(communityConfig),
      aboutConfig: JSON.stringify(aboutConfig),
      postCardConfig: JSON.stringify(postCardConfig),
      bannerConfig: JSON.stringify(bannerConfig),
    }

    // Reset hasChanges flag
    hasChanges = false

    // Show success notification
    saveStatus.success = true
    saveStatus.error = null

    // Reset success message after a delay
    setTimeout(() => {
      saveStatus.success = false
    }, 3000)
  } else if (error) {
    console.error('GitHub save error:', error)
    saveStatus.error = `GitHub save error: ${error}`
    saveStatus.success = false

    // Reset error message after a delay
    setTimeout(() => {
      saveStatus.error = null
    }, 5000)
  }
}

// Handle GitHub deployment events
function handleGitHubDeploy(event) {
  const { success, error } = event.detail

  if (success) {
    saveStatus.success = true
    saveStatus.error = null

    // Reset success message after a delay
    setTimeout(() => {
      saveStatus.success = false
    }, 3000)
  } else if (error) {
    console.error('GitHub deploy error:', error)
    saveStatus.error = `GitHub deploy error: ${error}`
    saveStatus.success = false

    // Reset error message after a delay
    setTimeout(() => {
      saveStatus.error = null
    }, 5000)
  }
}

// On component mount
onMount(() => {
  // Check for saved config in localStorage (for demo/persistence)
  try {
    // Initialize configs if they're undefined
    if (!avatarConfig) {
      avatarConfig = {
        avatarList: [],
        homeAvatar: '',
        animationInterval: 3500,
      }
    }

    if (!communityConfig) {
      communityConfig = {
        hero: {
          title: 'Join Our Community',
          description:
            'Connect with other members, share ideas, get help, and stay updated on the latest developments.',
          showGraphic: false,
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
          formFields: { name: {}, email: {}, subject: {}, message: {} },
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
    }

    if (!aboutConfig) {
      aboutConfig = {
        team: {
          enabled: true,
          title: 'Our Team',
          description: 'Meet the people behind the project',
          layout: 'grid',
          columns: {
            mobile: 1,
            tablet: 2,
            desktop: 3,
          },
          showEmail: true,
          showRole: true,
          avatarShape: 'rounded',
        },
        content: {
          enabled: true,
          defaultTitle: 'About The Project',
          showTableOfContents: true,
        },
        contact: {
          enabled: true,
          title: 'Get In Touch',
          description:
            "Have questions, ideas, or want to collaborate? We'd love to hear from you!",
          contactInfo: {
            email: 'contact@example.com',
          },
          displayOrder: ['description', 'email'],
        },
      }
    }

    if (!postCardConfig) {
      postCardConfig = {
        localPosts: {
          layout: {
            imagePosition: 'right',
            imageSizePercentage: 28,
            cardBorderRadius: 'rounded-[var(--radius-large)]',
            showEnterButton: true,
          },
          styling: {
            titleSize: 'text-3xl',
            descriptionLines: 2,
            animationEnabled: true,
          },
          content: {
            showCategory: true,
            showTags: true,
            showUpdateDate: true,
            showWordCount: true,
            showReadTime: true,
            hideTagsOnMobile: true,
          },
        },
        friendPosts: {
          layout: {
            imagePosition: 'right',
            imageSizePercentage: 28,
            cardBorderRadius: 'rounded-[var(--radius-large)]',
            showEnterButton: true,
          },
          styling: {
            titleSize: 'text-3xl',
            descriptionLines: 2,
            animationEnabled: true,
          },
          content: {
            showCategory: true,
            showTags: true,
            showUpdateDate: true,
            showWordCount: true,
            showReadTime: true,
            hideTagsOnMobile: true,
          },
          friendStyling: {
            indicatorType: 'border',
            indicatorColor: 'var(--primary)',
            showFriendAvatar: true,
            avatarSize: 'w-5 h-5',
          },
          attribution: {
            showAttribution: true,
            attributionText: 'Shared from [friendName]',
            linkToFriendSite: true,
          },
          behavior: {
            sortingMethod: 'date',
            mergeWithLocalPosts: true,
          },
        },
      }
    }

    // Initialize banner config if it doesn't exist
    if (!bannerConfig) {
      bannerConfig = {
        bannerList: [
          'src/assets/banner/0001.png',
          'src/assets/banner/0002.png',
          'src/assets/banner/0003.png',
          'src/assets/banner/0004.png',
          'src/assets/banner/0005.png',
          'src/assets/banner/0006.png',
          'src/assets/banner/0007.png',
          'src/assets/banner/0008.png',
        ],
        defaultBanner: 'src/assets/banner/0001.png',
        animation: {
          enabled: true,
          interval: 5000,
          transitionDuration: 1000,
          direction: 'alternate',
        },
        layout: {
          height: {
            desktop: '50vh',
            mobile: '30vh',
          },
          overlap: {
            desktop: '3.5rem',
            mobile: '2rem',
          },
          maxWidth: 3840,
        },
        visual: {
          objectFit: 'cover',
          objectPosition: 'center',
          applyGradientOverlay: false,
          gradientOverlay:
            'linear-gradient(to bottom, rgba(0,0,0,0.2), transparent)',
          borderRadius: '0',
        },
        fallback: {
          enabled: true,
          type: 'gradient',
          value:
            'linear-gradient(to bottom, var(--color-primary-light), var(--color-primary))',
        },
      }
    }

    // Initialize addons config if it doesn't exist
    if (!addonsConfig) {
      addonsConfig = {
        enabled: false,
        availableAddons: [],
        installedAddons: [],
      }
    }

    // Load saved configs from localStorage if they exist
    const savedSiteConfig = localStorage.getItem('siteConfig')
    if (savedSiteConfig && savedSiteConfig !== 'undefined') {
      siteConfig = { ...siteConfig, ...JSON.parse(savedSiteConfig) }
    }

    const savedNavConfig = localStorage.getItem('navBarConfig')
    if (savedNavConfig && savedNavConfig !== 'undefined') {
      navBarConfig = { ...navBarConfig, ...JSON.parse(savedNavConfig) }
    }

    const savedProfileConfig = localStorage.getItem('profileConfig')
    if (savedProfileConfig && savedProfileConfig !== 'undefined') {
      profileConfig = { ...profileConfig, ...JSON.parse(savedProfileConfig) }
    }

    const savedLicenseConfig = localStorage.getItem('licenseConfig')
    if (savedLicenseConfig && savedLicenseConfig !== 'undefined') {
      licenseConfig = { ...licenseConfig, ...JSON.parse(savedLicenseConfig) }
    }

    const savedTimelineConfig = localStorage.getItem('timelineConfig')
    if (savedTimelineConfig && savedTimelineConfig !== 'undefined') {
      timelineConfig = { ...timelineConfig, ...JSON.parse(savedTimelineConfig) }
    }

    const savedAvatarConfig = localStorage.getItem('avatarConfig')
    if (savedAvatarConfig && savedAvatarConfig !== 'undefined') {
      avatarConfig = { ...avatarConfig, ...JSON.parse(savedAvatarConfig) }
    }

    const savedCommunityConfig = localStorage.getItem('communityConfig')
    if (savedCommunityConfig && savedCommunityConfig !== 'undefined') {
      communityConfig = {
        ...communityConfig,
        ...JSON.parse(savedCommunityConfig),
      }
    }

    const savedAboutConfig = localStorage.getItem('aboutConfig')
    if (savedAboutConfig && savedAboutConfig !== 'undefined') {
      aboutConfig = { ...aboutConfig, ...JSON.parse(savedAboutConfig) }
    }

    const savedPostCardConfig = localStorage.getItem('postCardConfig')
    if (savedPostCardConfig && savedPostCardConfig !== 'undefined') {
      postCardConfig = { ...postCardConfig, ...JSON.parse(savedPostCardConfig) }
    }

    const savedBannerConfig = localStorage.getItem('bannerConfig')
    if (savedBannerConfig && savedBannerConfig !== 'undefined') {
      bannerConfig = { ...bannerConfig, ...JSON.parse(savedBannerConfig) }
    }

    const savedAddonsConfig = localStorage.getItem('addonsConfig')
    if (savedAddonsConfig && savedAddonsConfig !== 'undefined') {
      addonsConfig = { ...addonsConfig, ...JSON.parse(savedAddonsConfig) }
    }

    // Store original values for change detection
    originalConfigValues = {
      siteConfig: JSON.stringify(siteConfig),
      navBarConfig: JSON.stringify(navBarConfig),
      profileConfig: JSON.stringify(profileConfig),
      licenseConfig: JSON.stringify(licenseConfig),
      timelineConfig: JSON.stringify(timelineConfig),
      avatarConfig: JSON.stringify(avatarConfig),
      communityConfig: JSON.stringify(communityConfig),
      aboutConfig: JSON.stringify(aboutConfig),
      postCardConfig: JSON.stringify(postCardConfig),
      bannerConfig: JSON.stringify(bannerConfig),
      addonsConfig: JSON.stringify(addonsConfig),
    }

    // Initialize GitHub integration
    if (githubIntegration) {
      githubIntegration.initialize()
    }
  } catch (error) {
    console.error('Error loading saved configuration:', error)
  }
})

// Check for changes in any config to enable/disable the save button
$: {
  if (
    originalConfigValues.siteConfig &&
    originalConfigValues.navBarConfig &&
    originalConfigValues.profileConfig &&
    originalConfigValues.licenseConfig &&
    originalConfigValues.timelineConfig &&
    originalConfigValues.avatarConfig &&
    originalConfigValues.communityConfig &&
    originalConfigValues.aboutConfig &&
    originalConfigValues.postCardConfig &&
    originalConfigValues.bannerConfig
  ) {
    try {
      const currentValues = {
        siteConfig: JSON.stringify(siteConfig),
        navBarConfig: JSON.stringify(navBarConfig),
        profileConfig: JSON.stringify(profileConfig),
        licenseConfig: JSON.stringify(licenseConfig),
        timelineConfig: JSON.stringify(timelineConfig),
        avatarConfig: JSON.stringify(avatarConfig),
        communityConfig: JSON.stringify(communityConfig),
        aboutConfig: JSON.stringify(aboutConfig),
        postCardConfig: JSON.stringify(postCardConfig),
        bannerConfig: JSON.stringify(bannerConfig),
        addonsConfig: JSON.stringify(addonsConfig),
      }

      hasChanges =
        currentValues.siteConfig !== originalConfigValues.siteConfig ||
        currentValues.navBarConfig !== originalConfigValues.navBarConfig ||
        currentValues.profileConfig !== originalConfigValues.profileConfig ||
        currentValues.licenseConfig !== originalConfigValues.licenseConfig ||
        currentValues.timelineConfig !== originalConfigValues.timelineConfig ||
        currentValues.avatarConfig !== originalConfigValues.avatarConfig ||
        currentValues.communityConfig !==
          originalConfigValues.communityConfig ||
        currentValues.aboutConfig !== originalConfigValues.aboutConfig ||
        currentValues.postCardConfig !== originalConfigValues.postCardConfig ||
        currentValues.bannerConfig !== originalConfigValues.bannerConfig ||
        currentValues.addonsConfig !== originalConfigValues.addonsConfig
    } catch (error) {
      console.error('Error checking for changes:', error)
      // If there's an error comparing, assume changes were made
      hasChanges = true
    }
  }
}
</script>
  
<!-- Main Configuration Panel -->
<div class="config-panel">
  <!-- Config Tabs Header -->
  <div class="card-base w-full rounded-[var(--radius-large)] overflow-hidden relative mb-4">
    <div class="p-6 md:p-9">
      <h1 class="text-3xl font-bold text-black/90 dark:text-white/90 mb-6">Site Configuration</h1>
      
      <div class="border-b border-neutral-200 dark:border-neutral-700 mb-6">
        <nav class="flex flex-wrap space-x-1 md:space-x-8" aria-label="Configuration Tabs">
          {#each tabs as tab}
            <button 
              id={`tab-${tab.id}`} 
              class="tab-button py-4 px-3 border-b-2 transition-colors font-medium flex items-center whitespace-nowrap
                     {activeTab === tab.id ? 
                       'border-[var(--primary)] text-[var(--primary)]' : 
                       'border-transparent text-neutral-500 hover:text-neutral-700 dark:hover:text-neutral-300'}"
              on:click={() => setActiveTab(tab.id)}
            >
              <span class="hidden md:inline mr-2">
                <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="w-5 h-5">
                  <!-- Dynamically determine which icon path to use -->
                  {#if tab.icon === 'mdi:cog-outline'}
                    <circle cx="12" cy="12" r="3"></circle>
                    <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"></path>
                  {:else if tab.icon === 'mdi:navigation'}
                    <polygon points="3 11 22 2 13 21 11 13 3 11"></polygon>
                  {:else if tab.icon === 'mdi:account'}
                    <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path>
                    <circle cx="12" cy="7" r="4"></circle>
                  {:else if tab.icon === 'mdi:palette-outline'}
                    <circle cx="13.5" cy="6.5" r="2.5"></circle>
                    <circle cx="19" cy="13" r="2.5"></circle>
                    <circle cx="6" cy="12" r="2.5"></circle>
                    <circle cx="14" cy="19.5" r="2.5"></circle>
                    <path d="M12 2C6.5 2 2 6.5 2 12s4.5 10 10 10c.926 0 1.648-.746 1.648-1.688 0-.437-.18-.835-.437-1.125-.29-.289-.438-.652-.438-1.125a1.64 1.64 0 0 1 1.668-1.668h1.996c3.051 0 5.555-2.503 5.555-5.554C21.965 6.012 17.461 2 12 2z"></path>
                  {:else if tab.icon === 'mdi:timeline'}
                    <line x1="12" y1="22" x2="12" y2="15"></line>
                    <path d="M6 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2h-2"></path>
                    <path d="M22 12H2"></path>
                    <path d="M12 7V2"></path>
                    <path d="M14 3l-2 2-2-2"></path>
                    <path d="M18 15v7"></path>
                    <path d="M18 22l-2-2"></path>
                    <path d="M18 22l2-2"></path>
                    <path d="M6 15v7"></path>
                    <path d="M6 22l-2-2"></path>
                    <path d="M6 22l2-2"></path>
                  {:else if tab.icon === 'mdi:account-group'}
                    <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"></path>
                    <circle cx="9" cy="7" r="4"></circle>
                    <path d="M23 21v-2a4 4 0 0 0-3-3.87"></path>
                    <path d="M16 3.13a4 4 0 0 1 0 7.75"></path>
                  {:else if tab.icon === 'mdi:information-outline'}
                    <circle cx="12" cy="12" r="10"></circle>
                    <line x1="12" y1="16" x2="12" y2="12"></line>
                    <line x1="12" y1="8" x2="12.01" y2="8"></line>
                  {:else if tab.icon === 'mdi:shield-outline'}
                    <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path> 
                  {:else if tab.icon === 'mdi:code-json'}
                    <polyline points="16 18 22 12 16 6"></polyline>
                    <polyline points="8 6 2 12 8 18"></polyline>
                    {:else if tab.icon === 'mdi:puzzle-outline'}
                    <path d="M22 9h-4v6h4v6h-4v-6h-4v6h-4v-6H6v6H2v-6h4v-6H2V3h4v6h4V3h4v6h4V3h4v6z"></path>
                  {/if}
                </svg>
              </span>
              {tab.label}
            </button>
          {/each}
        </nav>
      </div>
      
      <!-- Tab Panels -->
      <div class="tab-panels">
        {#if activeTab === 'general'}
          <GeneralConfigTab 
            bind:siteConfig 
            bind:licenseConfig 
            on:change={() => hasChanges = true} 
          />
        {:else if activeTab === 'navigation'}
          <NavigationConfigTab 
            bind:navBarConfig 
            on:change={() => hasChanges = true} 
          />
        {:else if activeTab === 'profile'}
          <ProfileConfigTab 
            bind:profileConfig 
            bind:avatarConfig
            on:change={() => hasChanges = true}
            on:avatarChange={() => hasChanges = true}
          />
        {:else if activeTab === 'appearance'}
          <AppearanceConfigTab 
            bind:siteConfig 
            bind:postCardConfig
            bind:bannerConfig
            on:change={() => hasChanges = true} 
          />
        {:else if activeTab === 'timeline'}
          <TimelineConfigTab 
            bind:timelineConfig 
            on:change={() => hasChanges = true} 
          />
        {:else if activeTab === 'community'}
          <CommunityConfigTab 
            bind:communityConfig 
            on:change={() => hasChanges = true} 
          />
        {:else if activeTab === 'about'}
          <AboutConfigTab 
            bind:aboutConfig 
            on:change={() => hasChanges = true} 
          />
          {:else if activeTab === 'security'}
          <SecurityConfigTab
            on:change={() => hasChanges = true}
          />
          {:else if activeTab === 'addons'}
          <AddonsConfigTab 
            bind:addonsConfig
            on:change={() => hasChanges = true} 
          />
        {:else if activeTab === 'advanced'}
          <AdvancedConfigTab 
            {siteConfig} 
            {navBarConfig} 
            {profileConfig} 
            {licenseConfig}
            {timelineConfig}
            {avatarConfig}
            {communityConfig}
            {aboutConfig}
            {postCardConfig}
            {bannerConfig}
            on:update={(e) => {
              // Handle updates from the advanced editor
              const { configType, newValue } = e.detail;
              if (configType === 'siteConfig') siteConfig = newValue;
              else if (configType === 'navBarConfig') navBarConfig = newValue;
              else if (configType === 'profileConfig') profileConfig = newValue;
              else if (configType === 'licenseConfig') licenseConfig = newValue;
              else if (configType === 'timelineConfig') timelineConfig = newValue;
              else if (configType === 'avatarConfig') avatarConfig = newValue;
              else if (configType === 'communityConfig') communityConfig = newValue;
              else if (configType === 'aboutConfig') aboutConfig = newValue;
              else if (configType === 'postCardConfig') postCardConfig = newValue;
              else if (configType === 'bannerConfig') bannerConfig = newValue;
              
              // Mark that changes have been made
              hasChanges = true;
            }}
          />
        {/if}
      </div>
      
      <!-- Save Button -->
      <div class="mt-8 border-t border-neutral-200 dark:border-neutral-700 pt-6">
        <div class="flex justify-between items-center">
          <!-- Status message -->
          <div class="text-sm">
            {#if saveStatus.saving}
              <span class="text-neutral-500 dark:text-neutral-400 flex items-center">
                <svg class="animate-spin mr-2 h-4 w-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                  <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                  <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                </svg>
                Saving changes...
              </span>
            {:else if saveStatus.success}
              <span class="text-green-600 dark:text-green-400 flex items-center">
                <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 mr-2" viewBox="0 0 20 20" fill="currentColor">
                  <path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd" />
                </svg>
                Configuration saved successfully!
              </span>
            {:else if saveStatus.error}
              <span class="text-red-600 dark:text-red-400 flex items-center">
                <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 mr-2" viewBox="0 0 20 20" fill="currentColor">
                  <path fill-rule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7 4a1 1 0 11-2 0 1 1 0 012 0zm-1-9a1 1 0 00-1 1v4a1 1 0 102 0V6a1 1 0 00-1-1z" clip-rule="evenodd" />
                </svg>
                {saveStatus.error}
              </span>
            {/if}
          </div>
          
          <button 
            on:click={saveAllConfiguration}
            disabled={saveStatus.saving || !hasChanges}
            class="py-2 px-6 bg-[var(--primary)] hover:opacity-90 text-white font-medium rounded-md transition-opacity flex items-center disabled:opacity-60"
            title={!hasChanges ? "No changes to save" : "Save your changes"}
          >
            <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 mr-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 7H5a2 2 0 00-2 2v9a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-3m-1 4l-3 3m0 0l-3-3m3 3V4" />
            </svg>
            {saveStatus.saving ? 'Saving...' : hasChanges ? 'Save Changes' : 'No Changes'}
          </button>
        </div>
      </div>
      
      <!-- GitHub Integration Component -->
      <div class="mt-4">
        <GitHubIntegration
          bind:this={githubIntegration}
          {siteConfig}
          {navBarConfig}
          {profileConfig}
          {licenseConfig}
          {timelineConfig}
          {avatarConfig}
          {communityConfig}
          {aboutConfig}
          {postCardConfig}
          {bannerConfig}
          {originalConfigValues}
          {hasChanges}
          on:configsaved={handleGitHubConfigSaved}
          on:deploy={handleGitHubDeploy}
        />
      </div>
    </div>
  </div>
</div>

<!-- General Config Exporter Dialog -->
<ConfigExporter
  bind:show={showConfigExporter}
  {siteConfig}
  {navBarConfig}
  {profileConfig}
  {licenseConfig}
  {timelineConfig}
  {avatarConfig}
  {communityConfig}
  {aboutConfig}
  on:close={() => showConfigExporter = false}
/>

<!-- Community Config Exporter Dialog -->
<CommunityConfigExporter
  bind:show={showCommunityConfigExporter}
  {communityConfig}
  on:close={() => showCommunityConfigExporter = false}
/>

<!-- About Config Exporter Dialog -->
<AboutConfigExporter
  bind:show={showAboutConfigExporter}
  {aboutConfig}
  on:close={() => showAboutConfigExporter = false}
/>

<!-- PostCard Config Exporter Dialog -->
<PostCardConfigExporter
  bind:show={showPostCardConfigExporter}
  {postCardConfig}
  on:close={() => showPostCardConfigExporter = false}
/>

<!-- Banner Config Exporter Dialog -->
<BannerConfigExporter
  bind:show={showBannerConfigExporter}
  {bannerConfig}
  on:close={() => showBannerConfigExporter = false}
/>
  
<style>
  /* Add any component-specific styles here */
  .tab-button {
    position: relative;
  }
  
  .tab-button::after {
    content: '';
    position: absolute;
    bottom: -2px;
    left: 0;
    width: 100%;
    height: 2px;
    background-color: transparent;
    transition: background-color 0.2s ease;
  }
  
  .tab-button.active::after {
    background-color: var(--primary);
  }
</style>