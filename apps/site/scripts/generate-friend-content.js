// Create this file at scripts/generate-friend-content.js

// This script should be run as part of your build process
// For example, add to package.json: "build": "node scripts/generate-friend-content.js && astro build"

const fs = require('fs');
const path = require('path');
const { globSync } = require('glob');
const matter = require('gray-matter');
const { siteConfig } = require('../src/config');

// Ensure the public directory exists
const publicDir = path.join(__dirname, '../public');
if (!fs.existsSync(publicDir)) {
  fs.mkdirSync(publicDir, { recursive: true });
}

// Function to extract content from MDX files
function extractContent() {
  // Find all MDX files in the content/posts directory
  const mdxFiles = globSync('content/posts/**/*.mdx');
  
  // Process each file
  const posts = mdxFiles.map(file => {
    // Read the file
    const content = fs.readFileSync(file, 'utf8');
    
    // Parse frontmatter
    const { data, content: mdxContent } = matter(content);
    
    // Extract a preview of the content (first 150 characters)
    const contentPreview = mdxContent.trim().slice(0, 150) + '...';
    
    // Create post object
    return {
      id: path.basename(file, '.mdx'),
      title: data.title || 'Untitled Post',
      slug: path.basename(file, '.mdx'),
      description: data.description || '',
      published: data.published || new Date().toISOString(),
      content: contentPreview,
      tags: data.tags || []
    };
  });
  
  return posts;
}

// Create the friend-content.json file
function generateFriendContent() {
  const posts = extractContent();
  
  const friendContent = {
    site: {
      name: siteConfig.title || 'My Blog',
      description: siteConfig.description || '',
      url: siteConfig.siteUrl || '',
      owner: siteConfig.author || '',
      avatar: siteConfig.avatar || '/favicon.png'
    },
    cors: true,
    version: '1.0',
    generated: new Date().toISOString(),
    posts: posts
  };
  
  // Write to public directory
  fs.writeFileSync(
    path.join(publicDir, 'friend-content.json'),
    JSON.stringify(friendContent, null, 2)
  );
  
  console.log(`✅ Generated friend-content.json with ${posts.length} posts`);
}

// Run the function
generateFriendContent();