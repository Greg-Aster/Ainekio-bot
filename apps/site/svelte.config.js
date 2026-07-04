import { vitePreprocess } from "@astrojs/svelte";

export default {
  // Enable runtime checks when not in production
  dev: process.env.NODE_ENV !== 'production',
  
  // Combine both preprocess configurations
  preprocess: vitePreprocess({
    postcss: true, // Ensure PostCSS processing is enabled
    script: true   // Keep script preprocessing enabled
  }),
  
  // Additional configuration options
  vitePlugin: {
    experimental: {
      // Use SvelteKit's browser-only build
      useVitePreprocess: true
    }
  }
};