// Keep all your original imports
import sitemap from "@astrojs/sitemap";
import svelte from "@astrojs/svelte";
import tailwind from "@astrojs/tailwind";
import swup from "@swup/astro";
import Compress from "astro-compress";
import icon from "astro-icon";
import { defineConfig } from "astro/config";
import rehypeAutolinkHeadings from "rehype-autolink-headings";
import rehypeComponents from "rehype-components";
import rehypeKatex from "rehype-katex";
import rehypeSlug from "rehype-slug";
import remarkDirective from "remark-directive";
import remarkGithubAdmonitionsToDirectives from "remark-github-admonitions-to-directives";
import remarkMath from "remark-math";
import remarkSectionize from "remark-sectionize";
import { AdmonitionComponent } from "./src/plugins/rehype-component-admonition.mjs";
import { GithubCardComponent } from "./src/plugins/rehype-component-github-card.mjs";
import { parseDirectiveNode } from "./src/plugins/remark-directive-rehype.js";
import { remarkExcerpt } from "./src/plugins/remark-excerpt.js";
import { remarkReadingTime } from "./src/plugins/remark-reading-time.mjs";
import mdx from "@astrojs/mdx";
import { fileURLToPath } from 'url';
import { existsSync } from 'fs';
import { dirname, join } from 'path';
import fs from 'fs';

// CORS middleware for friend content sharing
const corsMiddleware = () => {
  return {
    name: 'cors-middleware',
    hooks: {
      'astro:server:setup': ({ server }) => {
        server.middlewares.use((req, res, next) => {
          // Check if the request is for an RSS feed or API endpoint
          if (req.url.includes('/rss.xml') || 
              req.url.includes('/feed.xml') || 
              req.url.includes('/feed') || 
              req.url.includes('/rss') || 
              req.url.includes('/atom.xml') ||
              req.url.includes('/api/') ||
              req.url.includes('/friend-content.json')) {
            
            // Set CORS headers
            res.setHeader('Access-Control-Allow-Origin', '*');
            res.setHeader('Access-Control-Allow-Methods', 'GET, OPTIONS');
            res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
            
            // Handle preflight requests
            if (req.method === 'OPTIONS') {
              res.statusCode = 204;
              return res.end();
            }
          }
          
          next();
        });
      },
      'astro:build:done': ({ pages, dir }) => {
        const outputDir = fileURLToPath(dir.href);
        
        // Create a client-side CORS proxy script that can be loaded by other sites
        const proxyJsPath = join(outputDir, 'cors-proxy.js');
        const proxyJsContent = `
/* CORS Proxy Helper for RSS feeds */
window.loadRSSCORS = function(url, callback) {
  // Try direct fetch first
  fetch(url, { 
    method: 'GET',
    headers: { 'Accept': 'application/xml, text/xml, application/rss+xml' },
    mode: 'cors'
  })
  .then(response => {
    if (response.ok) return response.text();
    throw new Error('CORS request failed');
  })
  .then(text => {
    const parser = new DOMParser();
    const doc = parser.parseFromString(text, 'text/xml');
    if (callback) callback(doc);
  })
  .catch(err => {
    // Fallback to a fetch with looser CORS policy
    console.log('Direct fetch failed, attempting alternative method');
    
    // Use alternate approach - create a temporary iframe
    const frame = document.createElement('iframe');
    frame.style.display = 'none';
    document.body.appendChild(frame);
    
    // Set timeout for cleanup
    const timeout = setTimeout(() => {
      try {
        document.body.removeChild(frame);
        if (callback) callback(null);
      } catch(e) {}
    }, 5000);
    
    // Setup message handler
    window.addEventListener('message', function messageHandler(event) {
      try {
        const data = event.data;
        if (data && data.rssProxyResponse && data.url === url) {
          // Clean up
          clearTimeout(timeout);
          window.removeEventListener('message', messageHandler);
          document.body.removeChild(frame);
          
          // Process data
          const parser = new DOMParser();
          const doc = parser.parseFromString(data.content, 'text/xml');
          if (callback) callback(doc);
        }
      } catch(e) {
        console.error('Error processing RSS proxy response', e);
        if (callback) callback(null);
      }
    });
    
    // Navigate iframe to a special URL that can read the content
    frame.src = url;
  });
};
        `.trim();
        
        fs.writeFileSync(proxyJsPath, proxyJsContent);
        console.log(`Created CORS proxy helper at ${proxyJsPath}`);
      }
    }
  };
};

// Base path and site URL configuration
let basePath = '/';
let siteUrl = 'https://ainek.io'; // Default fallback
const explicitSiteUrl = process.env.SITE_URL;
const explicitBasePath = process.env.SITE_BASE;

// Get current directory properly in ES module context
const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const cnamePath = join(__dirname, 'CNAME');

// Check if CNAME exists and read its content
let customDomain = null;
if (explicitSiteUrl) {
  siteUrl = explicitSiteUrl;
  basePath = explicitBasePath || '/';
  console.log(`Using explicit site override: ${siteUrl}${basePath}`);
} else {
  if (existsSync(cnamePath)) {
    try {
      // Use fs directly instead of require('fs')
      const cnameContent = fs.readFileSync(cnamePath, 'utf-8');
      // Clean the content (remove whitespace, etc.)
      customDomain = cnameContent.trim();
      
      if (customDomain) {
        siteUrl = `https://${customDomain}`;
        console.log(`Using custom domain from CNAME: ${siteUrl}`);
      }
    } catch (error) {
      console.warn('Error reading CNAME file:', error);
    }
  }
  
  // Auto-detect GitHub Pages environment if no custom domain was found or for subpath
  const GITHUB_REPOSITORY = process.env.GITHUB_REPOSITORY;
  
  if (GITHUB_REPOSITORY) {
    const [username, repo] = GITHUB_REPOSITORY.split('/');
    
    if (!customDomain) {
      // No custom domain, use GitHub Pages domain
      siteUrl = `https://${username}.github.io`;
      basePath = `/${repo}/`;
      console.log(`Detected GitHub Pages deployment: ${siteUrl}${basePath}`);
    } else {
      // Has custom domain, but still need basePath for subpaths
      basePath = '/';
      console.log(`Using custom domain without subpath: ${siteUrl}${basePath}`);
    }
  } else {
    // If not in GitHub Actions, use the default site URL
    console.log(`Using domain: ${siteUrl} with base: ${basePath}`);
  }
}

// https://astro.build/config
export default defineConfig({
  site: siteUrl,
  base: basePath,
  trailingSlash: "always",
  integrations: [
    corsMiddleware(), // Add the CORS middleware as an integration
    tailwind(
      {
        nesting: true,
      }
    ), 
    swup({
      theme: false,
      animationClass: "transition-swup-", // see https://swup.js.org/options/#animationselector
      // the default value `transition-` cause transition delay
      // when the Tailwind class `transition-all` is used
      containers: ["#banner-container", "#main-grid"],
      smoothScrolling: true,
      cache: true,
      preload: true,
      accessibility: true,
      updateHead: true,
      updateBodyClass: false,
      globalInstance: true,
    }), 
    icon({
      include: {
        "preprocess: viteProcess(),": ["*"],
        "fa6-brands": ["*"],
        "fa6-regular": ["*"],
        "fa6-solid": ["*"],
      },
    }), 
    svelte(), 
    sitemap({
      filter: (page) => {
        const { pathname } = new URL(page);
        return !(
          pathname.startsWith('/feed') ||
          pathname.startsWith('/rss') ||
          pathname.startsWith('/atom') ||
          pathname === '/new-post/' ||
          pathname === '/configs/' ||
          pathname === '/friends/' ||
          pathname === '/feed.xml' ||
          pathname === '/rss.xml' ||
          pathname === '/atom.xml'
        );
      },
    }), 
    Compress({
      CSS: false,
      Image: false,
      Action: {
        Passed: async () => true, // https://github.com/PlayForm/Compress/issues/376
      },
    }), 
    mdx()
  ],
  markdown: {
    remarkPlugins: [
      remarkMath,
      remarkReadingTime,
      remarkExcerpt,
      remarkGithubAdmonitionsToDirectives,
      remarkDirective,
      remarkSectionize,
      parseDirectiveNode,
    ],
    rehypePlugins: [
      rehypeKatex,
      rehypeSlug,
      [
        rehypeComponents,
        {
          components: {
            github: GithubCardComponent,
            note: (x, y) => AdmonitionComponent(x, y, "note"),
            tip: (x, y) => AdmonitionComponent(x, y, "tip"),
            important: (x, y) => AdmonitionComponent(x, y, "important"),
            caution: (x, y) => AdmonitionComponent(x, y, "caution"),
            warning: (x, y) => AdmonitionComponent(x, y, "warning"),
          },
        },
      ],
      [
        rehypeAutolinkHeadings,
        {
          behavior: "append",
          properties: {
            className: ["anchor"],
          },
          content: {
            type: "element",
            tagName: "span",
            properties: {
              className: ["anchor-icon"],
              "data-pagefind-ignore": true,
            },
            children: [
              {
                type: "text",
                value: "#",
              },
            ],
          },
        },
      ],
    ],
  },
  vite: {
    ssr: {
      noExternal: [/^@fontsource/, 'katex'],
    },
    optimizeDeps: {
      include: ['mammoth']
    },
    server: {
      // Add CORS headers to the dev server
      cors: {
        origin: '*',
        methods: ['GET', 'OPTIONS'],
        allowedHeaders: ['Content-Type'],
      },
    },
    build: {
      rollupOptions: {
        onwarn(warning, warn) {
          // temporarily suppress this warning
          if (
            warning.message.includes("is dynamically imported by") &&
            warning.message.includes("but also statically imported by")
          ) {
            return;
          }
          warn(warning);
        },
      },
    },
  },
});
