import { z } from 'zod'

export const postsSchema = z.object({
  title: z.string(),
  published: z.date(),
  updated: z.date().optional(),
  draft: z.boolean().optional().default(false),
  description: z.string().optional().default(''),
  image: z.string().optional().default(''),
  avatarImage: z.string().optional(),
  authorName: z.string().optional(),
  authorBio: z.string().optional(),
  authorLink: z.string().optional(),
  tags: z.array(z.string()).optional().default([]),
  category: z.string().optional().default(''),
  lang: z.string().optional().default(''),
  showImageOnPost: z.boolean().optional(),
  downloadable: z.boolean().optional().default(false),
  mascotContext: z.string().optional(),
  oneColumn: z.boolean().optional().default(false),
  showToc: z.boolean().optional(),
  backgroundImage: z.string().optional(),
  bannerType: z.enum(['image', 'video', 'timeline', 'assistant']).optional(),
  bannerLink: z.string().optional(),
  bannerData: z
    .object({
      videoId: z.string().optional(),
      imageUrl: z.string().optional(),
      category: z.string().optional(),
      startYear: z.number().optional(),
      endYear: z.number().optional(),
      background: z.string().optional(),
      title: z.string().optional(),
      height: z.string().optional(),
      compact: z.boolean().optional(),
    })
    .optional(),
  timelineYear: z.number().optional(),
  timelineEra: z.string().optional(),
  timelineLocation: z.string().optional(),
  isKeyEvent: z.boolean().optional(),
  yIndex: z.number().optional(),
  prevTitle: z.string().default(''),
  prevSlug: z.string().default(''),
  nextTitle: z.string().default(''),
  nextSlug: z.string().default(''),
})

export const specSchema = z.object({
  title: z.string(),
  description: z.string().optional(),
})

export const teamSchema = z.object({
  name: z.string(),
  role: z.string(),
  image: z.string(),
  email: z.string(),
  featured: z.boolean().optional(),
  order: z.number().default(0),
})

export const friendsSchema = z.object({
  name: z.string(),
  url: z.string(),
  bio: z.string().optional(),
  avatar: z.string().optional(),
  lastSynced: z.string().optional(),
})

export const updatesSchema = z.object({
  title: z.string().optional().default('Updates'),
  // statusTitle: z.string().optional().default('Current Status'),
  journalTitle: z.string().optional().default('Journal'),
  labels: z
    .object({
      status: z.string().optional(),
      location: z.string().optional(),
      section: z.string().optional(),
      mileage: z.string().optional(),
      nextStop: z.string().optional(),
      updated: z.string().optional(),
    })
    .optional(),
  maxEntries: z.number().optional().default(5),
  current: z
    .object({
      status: z.string().optional(),
      location: z.string().optional(),
      updated: z.date().optional(),
      mileage: z.string().optional(),
      section: z.string().optional(),
      nextStop: z.string().optional(),
      note: z.string().optional(),
    })
    .optional(),
  entries: z
    .array(
      z.object({
        title: z.string().optional(),
        date: z.date(),
        location: z.string().optional(),
        mileage: z.string().optional(),
        summary: z.string(),
        url: z.string().optional(),
      }),
    )
    .optional()
    .default([]),
})

export const aboutSchema = z.object({
  title: z.string(),
  description: z.string().optional(),
  name: z.string(),
  role: z.string().optional(),
  avatar: z.string().optional(),
  bio: z.string().optional(),
  published: z.date().optional(),
  updated: z.date().optional(),
  tags: z.array(z.string()).optional().default([]),
  category: z.string().optional().default(''),
  showImageOnPost: z.boolean().optional(),
  oneColumn: z.boolean().optional().default(false),
  socialLinks: z
    .array(
      z.object({
        name: z.string(),
        url: z.string(),
        icon: z.string(),
      }),
    )
    .optional()
    .default([]),
  backgroundImage: z.string().optional(),
  bannerType: z.enum(['image', 'video', 'timeline', 'assistant']).optional(),
  bannerData: z
    .object({
      videoId: z.string().optional(),
      imageUrl: z.string().optional(),
      category: z.string().optional(),
      startYear: z.number().optional(),
      endYear: z.number().optional(),
      background: z.string().optional(),
    })
    .optional(),
})

export const assetDataSchema = z.object({
  name: z.string().optional(),
})
