<script lang="ts">
  import { onMount, createEventDispatcher } from 'svelte';
  import type { CommunityConfig } from '../types/communityconfig';
  
  // Props
  export let communityConfig: CommunityConfig;
  
  // Event dispatcher to notify parent of changes
  const dispatch = createEventDispatcher();
  
  // Local state
  let activeSection = 'general';
  let editFeature: any = null;
  let editChannel: any = null;
  let editGuideline: string = '';
  let guidelineIndex: number = -1;
  let showFeatureEditor = false;
  let showChannelEditor = false;
  let showGuidelineEditor = false;
  
  // Sections for tab navigation
  const sections = [
    { id: 'general', label: 'General' },
    { id: 'discord', label: 'Discord' },
    { id: 'contact', label: 'Contact' },
    { id: 'newsletter', label: 'Newsletter' },
    { id: 'events', label: 'Events' },
    { id: 'guidelines', label: 'Guidelines' }
  ];
  
  // Function to notify parent of changes
  function notifyChanges() {
    dispatch('change');
  }
  
  // Function to toggle a section's enabled status
  function toggleSection(section: keyof CommunityConfig) {
    communityConfig[section].enabled = !communityConfig[section].enabled;
    notifyChanges();
  }
  
  // Function to toggle a hero option
  function toggleHeroOption(index: number) {
    communityConfig.hero.options[index].enabled = !communityConfig.hero.options[index].enabled;
    notifyChanges();
  }
  
  // Function to edit a feature
  function editFeatureItem(section: string, index: number) {
    const sectionKey = section as keyof CommunityConfig;
    editFeature = {
      section: section,
      index: index,
      ...communityConfig[sectionKey].features[index]
    };
    showFeatureEditor = true;
  }
  
  // Function to save feature changes
  function saveFeature() {
    if (editFeature) {
      const sectionKey = editFeature.section as keyof CommunityConfig;
      communityConfig[sectionKey].features[editFeature.index] = {
        title: editFeature.title,
        description: editFeature.description,
        icon: editFeature.icon
      };
      notifyChanges();
      showFeatureEditor = false;
    }
  }
  
  // Function to edit a discord channel
  function editDiscordChannel(index: number) {
    editChannel = {
      index: index,
      ...communityConfig.discord.channels[index]
    };
    showChannelEditor = true;
  }
  
  // Function to save channel changes
  function saveChannel() {
    if (editChannel) {
      communityConfig.discord.channels[editChannel.index] = {
        name: editChannel.name,
        description: editChannel.description,
        color: editChannel.color
      };
      notifyChanges();
      showChannelEditor = false;
    }
  }
  
  // Function to add a new channel
  function addChannel() {
    editChannel = {
      index: communityConfig.discord.channels.length,
      name: "#new-channel",
      description: "Channel description",
      color: "blue-500"
    };
    showChannelEditor = true;
  }
  
  // Function to delete a channel
  function deleteChannel(index: number) {
    if (confirm("Are you sure you want to delete this channel?")) {
      communityConfig.discord.channels = communityConfig.discord.channels.filter((_, i) => i !== index);
      notifyChanges();
    }
  }
  
  // Function to add a new guideline
  function addGuideline() {
    editGuideline = "";
    guidelineIndex = -1;
    showGuidelineEditor = true;
  }
  
  // Function to edit a guideline
  function editGuidelineItem(index: number) {
    editGuideline = communityConfig.guidelines.items[index];
    guidelineIndex = index;
    showGuidelineEditor = true;
  }
  
  // Function to save guideline
  function saveGuideline() {
    if (guidelineIndex === -1) {
      // Add new guideline
      communityConfig.guidelines.items = [...communityConfig.guidelines.items, editGuideline];
    } else {
      // Update existing guideline
      communityConfig.guidelines.items[guidelineIndex] = editGuideline;
    }
    showGuidelineEditor = false;
    notifyChanges();
  }
  
  // Function to delete a guideline
  function deleteGuideline(index: number) {
    if (confirm("Are you sure you want to delete this guideline?")) {
      communityConfig.guidelines.items = communityConfig.guidelines.items.filter((_, i) => i !== index);
      notifyChanges();
    }
  }
</script>

<div class="community-config-tab">
  <div class="mb-6">
    <h2 class="text-xl font-semibold text-black/80 dark:text-white/80 mb-4">Community Page Configuration</h2>
    <p class="text-neutral-600 dark:text-neutral-400 mb-4">
      Configure your community page sections, features, and content.
    </p>
    
    <!-- Section Tabs -->
    <div class="flex flex-wrap mb-6 space-x-2 md:space-x-4 border-b border-neutral-200 dark:border-neutral-700">
      {#each sections as section}
        <button 
          class="py-2 px-3 md:px-4 text-sm md:text-base {activeSection === section.id ? 'text-[var(--primary)] border-b-2 border-[var(--primary)]' : 'text-neutral-600 dark:text-neutral-400'}"
          on:click={() => activeSection = section.id}
        >
          {section.label}
        </button>
      {/each}
    </div>
    
    <!-- General Section (Hero) -->
    {#if activeSection === 'general'}
      <div class="general-section space-y-6">
        <div class="card bg-white dark:bg-neutral-800 p-5 rounded-lg border border-neutral-200 dark:border-neutral-700">
          <h3 class="font-medium text-lg text-black/80 dark:text-white/80 mb-4">Hero Section</h3>
          
          <div class="mb-4">
            <label class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
              Title
            </label>
            <input 
              type="text" 
              bind:value={communityConfig.hero.title} 
              on:input={notifyChanges}
                class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm text-neutral-800 dark:text-neutral-200"
            />
          </div>
          
          <div class="mb-4">
            <label class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
              Description
            </label>
            <textarea 
              bind:value={communityConfig.hero.description} 
              on:input={notifyChanges}
              rows="3" 
                class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm text-neutral-800 dark:text-neutral-200"
            ></textarea>
          </div>
          
          <div class="mb-4">
            <label class="flex items-center text-sm font-medium text-neutral-700 dark:text-neutral-300">
              <input 
                type="checkbox" 
                bind:checked={communityConfig.hero.showGraphic} 
                on:change={notifyChanges}
                class="mr-2 h-4 w-4"
              />
              Show Hero Graphic
            </label>
          </div>
          
          <h4 class="font-medium text-base mb-3 mt-6 text-neutral-800 dark:text-neutral-200">

Quick Access Options</h4>
          
          <div class="space-y-3">
            {#each communityConfig.hero.options as option, index}
              <div class="flex items-center justify-between p-3 rounded-lg border border-neutral-200 dark:border-neutral-700">
                <div class="flex items-center">
                  <input 
                    type="checkbox" 
                    checked={option.enabled} 
                    on:change={() => toggleHeroOption(index)}
                    class="mr-3 h-4 w-4"
                  />
                  <div>
                    <div class="font-medium text-neutral-800 dark:text-neutral-200">{option.title}</div>
                    <div class="text-xs text-neutral-500 dark:text-neutral-400">{option.description}</div>
                  </div>
                </div>
                <div class="text-sm text-neutral-500">
                  Links to: #{option.sectionId}
                </div>
              </div>
            {/each}
          </div>
        </div>
        
        <!-- Match Original Layout Helper for General Tab -->
        <div class="mt-8 card bg-white dark:bg-neutral-800 p-5 rounded-lg border border-neutral-200 dark:border-neutral-700">
          <h3 class="font-medium text-lg text-black/80 dark:text-white/80 mb-4">Match Original Layout</h3>
          <p class="text-neutral-600 dark:text-neutral-400 mb-4">
            Use this option to restore the exact configuration from the original community.astro file.
          </p>
          
          <button 
            class="py-2 px-4 bg-amber-500 hover:bg-amber-600 text-white font-medium rounded-md transition-colors flex items-center"
            on:click={() => {
              // Set configuration to match original community.astro layout
              communityConfig.hero = {
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
              };
              
              communityConfig.discord = {
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
              };
              
              communityConfig.contact = {
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
              };
              
              communityConfig.newsletter = {
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
              };
              
              communityConfig.events = {
                enabled: false,
                title: "Community Events",
                description: "Join our regular community events to learn, share, and connect with other members. From workshops to casual meetups, there's something for everyone.",
                calendarButtonText: "View Full Event Calendar",
                calendarUrl: "#"
              };
              
              communityConfig.guidelines = {
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
              };
              
              notifyChanges();
            }}
          >
            <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 mr-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
            </svg>
            Restore Original Layout
          </button>
          
          <div class="mt-4 text-sm text-neutral-500 dark:text-neutral-400">
            <p>This will configure the community page to exactly match the original design with:</p>
            <ul class="list-disc ml-5 mt-2 space-y-1">
              <li>Hero section with Discord and Contact options</li>
              <li>Discord section with features and channel overview</li>
              <li>Contact form with all fields</li>
              <li>Community guidelines section</li>
            </ul>
          </div>
        </div>
      </div>
    
    <!-- Discord Section -->
    {:else if activeSection === 'discord'}
      <div class="discord-section space-y-6">
        <div class="card bg-white dark:bg-neutral-800 p-5 rounded-lg border border-neutral-200 dark:border-neutral-700">
          <div class="flex justify-between items-center mb-4">
            <h3 class="font-medium text-lg text-black/80 dark:text-white/80">Discord Section</h3>
            <label class="flex items-center">
              <input 
                type="checkbox" 
                bind:checked={communityConfig.discord.enabled} 
                on:change={notifyChanges}
                class="mr-2 h-4 w-4"
              />
              <span class="text-sm font-medium text-neutral-700 dark:text-neutral-300">Enabled</span>
            </label>
          </div>
          
          <div class="mb-4">
            <label class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
              Section Title
            </label>
            <input 
              type="text" 
              bind:value={communityConfig.discord.title} 
              on:input={notifyChanges}
                class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm text-neutral-800 dark:text-neutral-200"
            />
          </div>
          
          <div class="mb-4">
            <label class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
              Description
            </label>
            <textarea 
              bind:value={communityConfig.discord.description} 
              on:input={notifyChanges}
              rows="3" 
                class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm text-neutral-800 dark:text-neutral-200"
            ></textarea>
          </div>
          
          <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
                Discord Invite URL
              </label>
              <input 
                type="text" 
                bind:value={communityConfig.discord.inviteUrl} 
                on:input={notifyChanges}
                  class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm text-neutral-800 dark:text-neutral-200"
              />
            </div>
            
            <div>
              <label class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
                Button Text
              </label>
              <input 
                type="text" 
                bind:value={communityConfig.discord.buttonText} 
                on:input={notifyChanges}
                  class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm text-neutral-800 dark:text-neutral-200"
              />
            </div>
          </div>
          
          <h4 class="font-medium text-base mb-3 mt-6 text-neutral-800 dark:text-neutral-200">

Discord Features</h4>
          
          <div class="space-y-3 mb-6">
            {#each communityConfig.discord.features as feature, index}
              <div class="flex justify-between items-start p-3 rounded-lg border border-neutral-200 dark:border-neutral-700">
                <div>
                  <h5 class="font-medium text-neutral-800 dark:text-neutral-200">{feature.title}</h5>
                  <p class="text-sm text-neutral-500 dark:text-neutral-400">{feature.description}</p>
                  <div class="text-xs text-neutral-400 mt-1">Icon: {feature.icon}</div>
                </div>
                <button 
                  class="p-1.5 text-neutral-500 hover:text-[var(--primary)] rounded-full"
                  on:click={() => editFeatureItem('discord', index)}
                >
                  <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                  </svg>
                </button>
              </div>
            {/each}
          </div>
          
          <h4 class="font-medium text-base mb-3 mt-6 text-neutral-800 dark:text-neutral-200">

Discord Channels</h4>
          
          <div class="space-y-3 mb-4">
            {#each communityConfig.discord.channels as channel, index}
              <div class="flex justify-between items-center p-3 rounded-lg border border-neutral-200 dark:border-neutral-700">
                <div class="flex items-center">
                  <span class="w-3 h-3 bg-{channel.color} rounded-full mr-2"></span>
                  <div>
                    <div class="font-medium text-neutral-800 dark:text-neutral-200">{channel.name}</div>
                    <div class="text-xs text-neutral-500 dark:text-neutral-400">{channel.description}</div>
                  </div>
                </div>
                <div class="flex space-x-2">
                  <button 
                    class="p-1.5 text-neutral-500 hover:text-[var(--primary)] rounded-full"
                    on:click={() => editDiscordChannel(index)}
                  >
                    <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                    </svg>
                  </button>
                  <button 
                    class="p-1.5 text-neutral-500 hover:text-red-500 rounded-full"
                    on:click={() => deleteChannel(index)}
                  >
                    <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                    </svg>
                  </button>
                </div>
              </div>
            {/each}
          </div>
          
          <button 
            class="py-1.5 px-3 bg-[var(--primary)] hover:opacity-90 text-white font-medium rounded-md transition-opacity text-sm flex items-center"
            on:click={addChannel}
          >
            <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 mr-1" viewBox="0 0 20 20" fill="currentColor">
              <path fill-rule="evenodd" d="M10 5a1 1 0 011 1v3h3a1 1 0 110 2h-3v3a1 1 0 11-2 0v-3H6a1 1 0 110-2h3V6a1 1 0 011-1z" clip-rule="evenodd" />
            </svg>
            Add Channel
          </button>
        </div>
      </div>
    
    <!-- Contact Section -->
    {:else if activeSection === 'contact'}
      <div class="contact-section space-y-6">
        <div class="card bg-white dark:bg-neutral-800 p-5 rounded-lg border border-neutral-200 dark:border-neutral-700">
          <div class="flex justify-between items-center mb-4">
            <h3 class="font-medium text-lg text-black/80 dark:text-white/80">Contact Section</h3>
            <label class="flex items-center">
              <input 
                type="checkbox" 
                bind:checked={communityConfig.contact.enabled} 
                on:change={notifyChanges}
                class="mr-2 h-4 w-4"
              />
              <span class="text-sm font-medium text-neutral-700 dark:text-neutral-300">Enabled</span>
            </label>
          </div>
          
          <div class="mb-4">
            <label class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
              Section Title
            </label>
            <input 
              type="text" 
              bind:value={communityConfig.contact.title} 
              on:input={notifyChanges}
                class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm text-neutral-800 dark:text-neutral-200"
            />
          </div>
          
          <div class="mb-4">
            <label class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
              Description
            </label>
            <textarea 
              bind:value={communityConfig.contact.description} 
              on:input={notifyChanges}
              rows="3" 
                class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm text-neutral-800 dark:text-neutral-200"
            ></textarea>
          </div>
          
          <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
                Form Action URL
              </label>
              <input 
                type="text" 
                bind:value={communityConfig.contact.formActionUrl} 
                on:input={notifyChanges}
                  class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm text-neutral-800 dark:text-neutral-200"
              />
              <p class="text-xs text-neutral-500 mt-1">e.g., Formspree endpoint</p>
            </div>
            
            <div>
              <label class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
                Button Text
              </label>
              <input 
                type="text" 
                bind:value={communityConfig.contact.buttonText} 
                on:input={notifyChanges}
                  class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm text-neutral-800 dark:text-neutral-200"
              />
            </div>
          </div>
          
          <h4 class="font-medium text-base mb-3 mt-6 text-neutral-800 dark:text-neutral-200">

Contact Features</h4>
          
          <div class="space-y-3 mb-6">
            {#each communityConfig.contact.features as feature, index}
              <div class="flex justify-between items-start p-3 rounded-lg border border-neutral-200 dark:border-neutral-700">
                <div>
                  <h5 class="font-medium text-neutral-800 dark:text-neutral-200">{feature.title}</h5>
                  <p class="text-sm text-neutral-500 dark:text-neutral-400">{feature.description}</p>
                  <div class="text-xs text-neutral-400 mt-1">Icon: {feature.icon}</div>
                </div>
                <button 
                  class="p-1.5 text-neutral-500 hover:text-[var(--primary)] rounded-full"
                  on:click={() => editFeatureItem('contact', index)}
                >
                  <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                  </svg>
                </button>
              </div>
            {/each}
          </div>
          
          <h4 class="font-medium text-base mb-3 mt-6 text-neutral-800 dark:text-neutral-200">

Form Field Settings</h4>
          
          <!-- Name Field -->
          <div class="mb-4 p-3 rounded-lg border border-neutral-200 dark:border-neutral-700">
            <h5 class="font-medium mb-2 text-neutral-800 dark:text-neutral-200">Name Field</h5>
            <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label class="block text-xs font-medium text-neutral-700 dark:text-neutral-300 mb-1">Label</label>
                <input 
                  type="text" 
                  bind:value={communityConfig.contact.formFields.name.label} 
                  on:input={notifyChanges}
                    class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm text-neutral-800 dark:text-neutral-200"
                />
              </div>
              <div>
                <label class="block text-xs font-medium text-neutral-700 dark:text-neutral-300 mb-1">Placeholder</label>
                <input 
                  type="text" 
                  bind:value={communityConfig.contact.formFields.name.placeholder} 
                  on:input={notifyChanges}
                    class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm text-neutral-800 dark:text-neutral-200"
                />
              </div>
            </div>
            <div class="mt-2">
              <label class="flex items-center text-xs font-medium text-neutral-700 dark:text-neutral-300">
                <input 
                  type="checkbox" 
                  bind:checked={communityConfig.contact.formFields.name.required} 
                  on:change={notifyChanges}
                  class="mr-2 h-4 w-4"
                />
                Required Field
              </label>
            </div>
          </div>
          
          <!-- Email Field -->
          <div class="mb-4 p-3 rounded-lg border border-neutral-200 dark:border-neutral-700">
            <h5 class="font-medium mb-2 text-neutral-800 dark:text-neutral-200">Email Field</h5>
            <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label class="block text-xs font-medium text-neutral-700 dark:text-neutral-300 mb-1">Label</label>
                <input 
                  type="text" 
                  bind:value={communityConfig.contact.formFields.email.label} 
                  on:input={notifyChanges}
                    class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm text-neutral-800 dark:text-neutral-200"
                />
              </div>
              <div>
                <label class="block text-xs font-medium text-neutral-700 dark:text-neutral-300 mb-1">Placeholder</label>
                <input 
                  type="text" 
                  bind:value={communityConfig.contact.formFields.email.placeholder} 
                  on:input={notifyChanges}
                    class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm text-neutral-800 dark:text-neutral-200"
                />
              </div>
            </div>
            <div class="mt-2">
              <label class="flex items-center text-xs font-medium text-neutral-700 dark:text-neutral-300">
                <input 
                  type="checkbox" 
                  bind:checked={communityConfig.contact.formFields.email.required} 
                  on:change={notifyChanges}
                  class="mr-2 h-4 w-4"
                />
                Required Field
              </label>
            </div>
          </div>
          
          <!-- Subject Field -->
          <div class="mb-4 p-3 rounded-lg border border-neutral-200 dark:border-neutral-700">
            <h5 class="font-medium mb-2 text-neutral-800 dark:text-neutral-200">Subject Field</h5>
            <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label class="block text-xs font-medium text-neutral-700 dark:text-neutral-300 mb-1">Label</label>
                <input 
                  type="text" 
                  bind:value={communityConfig.contact.formFields.subject.label} 
                  on:input={notifyChanges}
                    class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm text-neutral-800 dark:text-neutral-200"
                />
              </div>
              <div>
                <label class="block text-xs font-medium text-neutral-700 dark:text-neutral-300 mb-1">Placeholder</label>
                <input 
                  type="text" 
                  bind:value={communityConfig.contact.formFields.subject.placeholder} 
                  on:input={notifyChanges}
                    class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm text-neutral-800 dark:text-neutral-200"
                />
              </div>
            </div>
            <div class="mt-2">
              <label class="flex items-center text-xs font-medium text-neutral-700 dark:text-neutral-300">
                <input 
                  type="checkbox" 
                  bind:checked={communityConfig.contact.formFields.subject.required} 
                  on:change={notifyChanges}
                  class="mr-2 h-4 w-4"
                />
                Required Field
              </label>
            </div>
          </div>
          
          <!-- Message Field -->
          <div class="mb-4 p-3 rounded-lg border border-neutral-200 dark:border-neutral-700">
            <h5 class="font-medium mb-2 text-neutral-800 dark:text-neutral-200">Message Field</h5>
            <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label class="block text-xs font-medium text-neutral-700 dark:text-neutral-300 mb-1">Label</label>
                <input 
                  type="text" 
                  bind:value={communityConfig.contact.formFields.message.label} 
                  on:input={notifyChanges}
                    class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm text-neutral-800 dark:text-neutral-200"
                />
              </div>
              <div>
                <label class="block text-xs font-medium text-neutral-700 dark:text-neutral-300 mb-1">Placeholder</label>
                <input 
                  type="text" 
                  bind:value={communityConfig.contact.formFields.message.placeholder} 
                  on:input={notifyChanges}
                    class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm text-neutral-800 dark:text-neutral-200"
                />
              </div>
            </div>
            <div class="grid grid-cols-1 md:grid-cols-2 gap-4 mt-2">
              <div>
                <label class="block text-xs font-medium text-neutral-700 dark:text-neutral-300 mb-1">Rows</label>
                <input 
                  type="number" 
                  bind:value={communityConfig.contact.formFields.message.rows} 
                  on:input={notifyChanges}
                  min="2" 
                  max="10" 
                    class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm text-neutral-800 dark:text-neutral-200"
                />
              </div>
              <div class="flex items-center">
                <label class="flex items-center text-xs font-medium text-neutral-700 dark:text-neutral-300">
                  <input 
                    type="checkbox" 
                    bind:checked={communityConfig.contact.formFields.message.required} 
                    on:change={notifyChanges}
                    class="mr-2 h-4 w-4"
                  />
                  Required Field
                </label>
              </div>
            </div>
          </div>
        </div>
      </div>
    
    <!-- Newsletter Section -->
    {:else if activeSection === 'newsletter'}
      <div class="newsletter-section space-y-6">
        <div class="card bg-white dark:bg-neutral-800 p-5 rounded-lg border border-neutral-200 dark:border-neutral-700">
          <div class="flex justify-between items-center mb-4">
            <h3 class="font-medium text-lg text-black/80 dark:text-white/80">Newsletter Section</h3>
            <label class="flex items-center">
              <input 
                type="checkbox" 
                bind:checked={communityConfig.newsletter.enabled} 
                on:change={notifyChanges}
                class="mr-2 h-4 w-4"
              />
              <span class="text-sm font-medium text-neutral-700 dark:text-neutral-300">Enabled</span>
            </label>
          </div>
          
          <div class="mb-4">
            <label class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
              Section Title
            </label>
            <input 
              type="text" 
              bind:value={communityConfig.newsletter.title} 
              on:input={notifyChanges}
                class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm text-neutral-800 dark:text-neutral-200"
            />
          </div>
          
          <div class="mb-4">
            <label class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
              Description
            </label>
            <textarea 
              bind:value={communityConfig.newsletter.description} 
              on:input={notifyChanges}
              rows="3" 
                class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm text-neutral-800 dark:text-neutral-200"
            ></textarea>
          </div>
          
          <div class="mb-4">
            <label class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
              Button Text
            </label>
            <input 
              type="text" 
              bind:value={communityConfig.newsletter.buttonText} 
              on:input={notifyChanges}
                class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm text-neutral-800 dark:text-neutral-200"
            />
          </div>
          
          <div class="mb-4">
            <label class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
              Consent Text
            </label>
            <textarea 
              bind:value={communityConfig.newsletter.consentText} 
              on:input={notifyChanges}
              rows="2" 
                class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm text-neutral-800 dark:text-neutral-200"
            ></textarea>
          </div>
          
          <h4 class="font-medium text-base mb-3 mt-6 text-neutral-800 dark:text-neutral-200">

Newsletter Features</h4>
          
          <div class="space-y-3 mb-6">
            {#each communityConfig.newsletter.features as feature, index}
              <div class="flex justify-between items-start p-3 rounded-lg border border-neutral-200 dark:border-neutral-700">
                <div>
                  <h5 class="font-medium text-neutral-800 dark:text-neutral-200">{feature.title}</h5>
                  <p class="text-sm text-neutral-500 dark:text-neutral-400">{feature.description}</p>
                  <div class="text-xs text-neutral-400 mt-1">Icon: {feature.icon}</div>
                </div>
                <button 
                  class="p-1.5 text-neutral-500 hover:text-[var(--primary)] rounded-full"
                  on:click={() => editFeatureItem('newsletter', index)}
                >
                  <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                  </svg>
                </button>
              </div>
            {/each}
          </div>
        </div>
      </div>
    
    <!-- Events Section -->
    {:else if activeSection === 'events'}
      <div class="events-section space-y-6">
        <div class="card bg-white dark:bg-neutral-800 p-5 rounded-lg border border-neutral-200 dark:border-neutral-700">
          <div class="flex justify-between items-center mb-4">
            <h3 class="font-medium text-lg text-black/80 dark:text-white/80">Events Section</h3>
            <label class="flex items-center">
              <input 
                type="checkbox" 
                bind:checked={communityConfig.events.enabled} 
                on:change={notifyChanges}
                class="mr-2 h-4 w-4"
              />
              <span class="text-sm font-medium text-neutral-700 dark:text-neutral-300">Enabled</span>
            </label>
          </div>
          
          <div class="mb-4">
            <label class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
              Section Title
            </label>
            <input 
              type="text" 
              bind:value={communityConfig.events.title} 
              on:input={notifyChanges}
                class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm text-neutral-800 dark:text-neutral-200"
            />
          </div>
          
          <div class="mb-4">
            <label class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
              Description
            </label>
            <textarea 
              bind:value={communityConfig.events.description} 
              on:input={notifyChanges}
              rows="3" 
                class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm text-neutral-800 dark:text-neutral-200"
            ></textarea>
          </div>
          
          <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
                Calendar URL
              </label>
              <input 
                type="text" 
                bind:value={communityConfig.events.calendarUrl} 
                on:input={notifyChanges}
                  class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm text-neutral-800 dark:text-neutral-200"
              />
            </div>
            
            <div>
              <label class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
                Calendar Button Text
              </label>
              <input 
                type="text" 
                bind:value={communityConfig.events.calendarButtonText} 
                on:input={notifyChanges}
                  class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm text-neutral-800 dark:text-neutral-200"
              />
            </div>
          </div>
          
          <div class="bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800/30 rounded-md p-3 text-amber-800 dark:text-amber-200 text-sm mt-6">
            <div class="flex">
              <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 mr-2 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
              </svg>
              <div>
                <p class="font-medium">Note about Events</p>
                <p class="mt-1">The events feature requires additional implementation to manage event listings. This section currently only controls the display of the events section and its content.</p>
              </div>
            </div>
          </div>
        </div>
      </div>
    
    <!-- Guidelines Section -->
    {:else if activeSection === 'guidelines'}
      <div class="guidelines-section space-y-6">
        <div class="card bg-white dark:bg-neutral-800 p-5 rounded-lg border border-neutral-200 dark:border-neutral-700">
          <div class="flex justify-between items-center mb-4">
            <h3 class="font-medium text-lg text-black/80 dark:text-white/80">Community Guidelines</h3>
            <label class="flex items-center">
              <input 
                type="checkbox" 
                bind:checked={communityConfig.guidelines.enabled} 
                on:change={notifyChanges}
                class="mr-2 h-4 w-4"
              />
              <span class="text-sm font-medium text-neutral-700 dark:text-neutral-300">Enabled</span>
            </label>
          </div>
          
          <div class="mb-4">
            <label class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
              Section Title
            </label>
            <input 
              type="text" 
              bind:value={communityConfig.guidelines.title} 
              on:input={notifyChanges}
                class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm text-neutral-800 dark:text-neutral-200"
            />
          </div>
          
          <div class="mb-4">
            <label class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
              Description
            </label>
            <textarea 
              bind:value={communityConfig.guidelines.description} 
              on:input={notifyChanges}
              rows="3" 
                class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm text-neutral-800 dark:text-neutral-200"
            ></textarea>
          </div>
          
          <h4 class="font-medium text-base mb-3 mt-6 text-neutral-800 dark:text-neutral-200">

Community Guidelines List</h4>
          
          <div class="space-y-3 mb-4">
            {#each communityConfig.guidelines.items as item, index}
              <div class="flex justify-between items-center p-3 rounded-lg border border-neutral-200 dark:border-neutral-700">
                <div class="flex items-center space-x-3">
                  <span class="text-neutral-500 dark:text-neutral-400">{index + 1}.</span>
                  <p class="text-sm text-neutral-800 dark:text-neutral-200">{item}</p>
                </div>
                <div class="flex space-x-2">
                  <button 
                    class="p-1.5 text-neutral-500 hover:text-[var(--primary)] rounded-full"
                    on:click={() => editGuidelineItem(index)}
                  >
                    <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                    </svg>
                  </button>
                  <button 
                    class="p-1.5 text-neutral-500 hover:text-red-500 rounded-full"
                    on:click={() => deleteGuideline(index)}
                  >
                    <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                    </svg>
                  </button>
                </div>
              </div>
            {/each}
          </div>
          
          <button 
            class="py-1.5 px-3 bg-[var(--primary)] hover:opacity-90 text-white font-medium rounded-md transition-opacity text-sm flex items-center"
            on:click={addGuideline}
          >
            <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 mr-1" viewBox="0 0 20 20" fill="currentColor">
              <path fill-rule="evenodd" d="M10 5a1 1 0 011 1v3h3a1 1 0 110 2h-3v3a1 1 0 11-2 0v-3H6a1 1 0 110-2h3V6a1 1 0 011-1z" clip-rule="evenodd" />
            </svg>
            Add Guideline
          </button>
        </div>
      </div>
    {/if}
  </div>
  
  <!-- Feature Editor Modal -->
  {#if showFeatureEditor}
    <div class="fixed inset-0 bg-black/50 dark:bg-black/60 z-50 flex items-center justify-center">
      <div class="bg-white dark:bg-neutral-800 rounded-lg max-w-md w-full p-6 shadow-lg">
        <h3 class="text-lg font-semibold text-black/80 dark:text-white/80 mb-4">Edit Feature</h3>
        
        <div class="mb-4">
          <label class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
            Feature Title
          </label>
          <input 
            type="text" 
            bind:value={editFeature.title} 
              class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm text-neutral-800 dark:text-neutral-200"
          />
        </div>
        
        <div class="mb-4">
          <label class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
            Description
          </label>
          <textarea 
            bind:value={editFeature.description} 
            rows="3" 
              class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm text-neutral-800 dark:text-neutral-200"
          ></textarea>
        </div>
        
        <div class="mb-6">
          <label class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
            Icon
          </label>
          <input 
            type="text" 
            bind:value={editFeature.icon} 
              class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm text-neutral-800 dark:text-neutral-200"
          />
          <p class="text-xs text-neutral-500 mt-1">e.g., mdi:chat-processing-outline</p>
        </div>
        
        <div class="flex justify-end space-x-3">
          <button 
            class="py-2 px-4 bg-neutral-200 dark:bg-neutral-700 hover:bg-neutral-300 dark:hover:bg-neutral-600 text-neutral-700 dark:text-neutral-200 font-medium rounded-md transition-colors"
            on:click={() => showFeatureEditor = false}
          >
            Cancel
          </button>
          
          <button 
            class="py-2 px-4 bg-[var(--primary)] hover:opacity-90 text-white font-medium rounded-md transition-opacity flex items-center"
            on:click={saveFeature}
          >
            Save Changes
          </button>
        </div>
      </div>
    </div>
  {/if}
  
  <!-- Channel Editor Modal -->
  {#if showChannelEditor}
    <div class="fixed inset-0 bg-black/50 dark:bg-black/60 z-50 flex items-center justify-center">
      <div class="bg-white dark:bg-neutral-800 rounded-lg max-w-md w-full p-6 shadow-lg">
        <h3 class="text-lg font-semibold text-black/80 dark:text-white/80 mb-4">
          {editChannel.index === communityConfig.discord.channels.length ? 'Add Channel' : 'Edit Channel'}
        </h3>
        
        <div class="mb-4">
          <label class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
            Channel Name
          </label>
          <input 
            type="text" 
            bind:value={editChannel.name} 
              class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm text-neutral-800 dark:text-neutral-200"
          />
        </div>
        
        <div class="mb-4">
          <label class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
            Description
          </label>
          <input 
            type="text" 
            bind:value={editChannel.description} 
              class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm text-neutral-800 dark:text-neutral-200"
          />
        </div>
        
        <div class="mb-6">
          <label class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
            Color
          </label>
          <select 
            bind:value={editChannel.color} 
              class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm text-neutral-800 dark:text-neutral-200"
          >
            <option value="green-500">Green</option>
            <option value="blue-500">Blue</option>
            <option value="purple-500">Purple</option>
            <option value="yellow-500">Yellow</option>
            <option value="red-500">Red</option>
            <option value="pink-500">Pink</option>
            <option value="indigo-500">Indigo</option>
          </select>
        </div>
        
        <div class="flex justify-end space-x-3">
          <button 
            class="py-2 px-4 bg-neutral-200 dark:bg-neutral-700 hover:bg-neutral-300 dark:hover:bg-neutral-600 text-neutral-700 dark:text-neutral-200 font-medium rounded-md transition-colors"
            on:click={() => showChannelEditor = false}
          >
            Cancel
          </button>
          
          <button 
            class="py-2 px-4 bg-[var(--primary)] hover:opacity-90 text-white font-medium rounded-md transition-opacity flex items-center"
            on:click={saveChannel}
          >
            {editChannel.index === communityConfig.discord.channels.length ? 'Add Channel' : 'Save Changes'}
          </button>
        </div>
      </div>
    </div>
  {/if}
  
  <!-- Guideline Editor Modal -->
  {#if showGuidelineEditor}
    <div class="fixed inset-0 bg-black/50 dark:bg-black/60 z-50 flex items-center justify-center">
      <div class="bg-white dark:bg-neutral-800 rounded-lg max-w-md w-full p-6 shadow-lg">
        <h3 class="text-lg font-semibold text-black/80 dark:text-white/80 mb-4">
          {guidelineIndex === -1 ? 'Add Guideline' : 'Edit Guideline'}
        </h3>
        
        <div class="mb-6">
          <label class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
            Guideline Text
          </label>
          <textarea 
            bind:value={editGuideline} 
            rows="3" 
              class="w-full px-3 py-2 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm text-neutral-800 dark:text-neutral-200"
          ></textarea>
        </div>
        
        <div class="flex justify-end space-x-3">
          <button 
            class="py-2 px-4 bg-neutral-200 dark:bg-neutral-700 hover:bg-neutral-300 dark:hover:bg-neutral-600 text-neutral-700 dark:text-neutral-200 font-medium rounded-md transition-colors"
            on:click={() => showGuidelineEditor = false}
          >
            Cancel
          </button>
          
          <button 
            class="py-2 px-4 bg-[var(--primary)] hover:opacity-90 text-white font-medium rounded-md transition-opacity flex items-center"
            on:click={saveGuideline}
          >
            {guidelineIndex === -1 ? 'Add Guideline' : 'Save Changes'}
          </button>
        </div>
      </div>
    </div>
  {/if}
</div>