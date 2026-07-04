<script>
  import { createEventDispatcher } from 'svelte';
  import AppearanceThemeSettings from './appearance/AppearanceThemeSettings.svelte';
  import BannerSettings from './appearance/BannerSettings.svelte';
  import PostCardSettings from './appearance/PostCardSettings.svelte';
  import FaviconSettings from './appearance/FaviconSettings.svelte';
  import TransparencySettings from './appearance/TransparencySettings.svelte';
  
  // Props
  export let siteConfig;
  export let postCardConfig;
  export let bannerConfig;
  
  // Event dispatcher
  const dispatch = createEventDispatcher();
  
  // Handle change events from child components
  function handleChange(event) {
    // Forward the change event to the parent
    dispatch('change', event.detail || siteConfig);
  }
</script>

<div class="appearance-config-tab">
  <div class="mb-6">
    <h2 class="text-xl font-semibold text-black/80 dark:text-white/80 mb-4">Appearance Settings</h2>
    <p class="text-neutral-600 dark:text-neutral-400 mb-4">
      Configure visual aspects of your site, including theme colors and icons.
    </p>
  </div>

  <!-- Theme Settings Section -->
  <AppearanceThemeSettings 
    bind:siteConfig={siteConfig} 
    on:change={handleChange} 
  />
  
  <!-- Transparency Settings Section -->
  <TransparencySettings
    bind:siteConfig={siteConfig}
    on:change={handleChange}
  />
  
  <!-- Banner Settings Section -->
  <BannerSettings 
    bind:bannerConfig={bannerConfig} 
    on:change={handleChange} 
  />
  
  <!-- Post Card Settings Section -->
  <PostCardSettings 
    bind:postCardConfig={postCardConfig} 
    on:change={handleChange} 
  />
  
  <!-- Favicon Settings Section -->
  <FaviconSettings 
    bind:siteConfig={siteConfig} 
    on:change={handleChange} 
  />
</div>