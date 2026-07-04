#!/usr/bin/env node
/**
 * Create a new blog post with today's date.
 * Usage: node scripts/new-post.js "My Post Title"
 */
import { writeFileSync, mkdirSync } from 'fs'
import { join, dirname } from 'path'
import { fileURLToPath } from 'url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const title = process.argv[2] || 'New Post'
const date = new Date().toISOString().split('T')[0]
const slug = title.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')
const filename = `${date}-${slug}.md`
const postsDir = join(__dirname, '..', 'src', 'content', 'posts')

mkdirSync(postsDir, { recursive: true })

const content = `---
title: "${title}"
published: ${date}
description: ""
tags: []
category: ""
---

Write your post here.
`

const filepath = join(postsDir, filename)
writeFileSync(filepath, content)
console.log(`Created: src/content/posts/${filename}`)
