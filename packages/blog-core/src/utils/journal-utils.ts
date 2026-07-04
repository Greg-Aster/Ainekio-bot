import { marked } from 'marked'

export type LegacyJournalEntry = {
  title?: string
  date: Date
  location?: string
  mileage?: string
  summary: string
  url?: string
}

export type ParsedJournalEntry = {
  title?: string
  date: Date
  location?: string
  mileage?: string
  contentMarkdown: string
  contentHtml: string
  excerpt: string
}

export type ParsedJournalContent = {
  introMarkdown: string
  introHtml: string
  entries: ParsedJournalEntry[]
  usesBodyEntries: boolean
}

type BodySection = {
  heading: string
  markdown: string
}

const DATE_PREFIX_PATTERN = /^(\d{4}-\d{2}-\d{2})(?:\s*(?:\||-|:)\s*(.+))?$/
const LOCATION_PATTERN = /^location\s*:\s*(.+)$/i
const MILEAGE_PATTERN = /^mileage\s*:\s*(.+)$/i

export async function parseJournalContent(
  body: string,
  legacyEntries: LegacyJournalEntry[] = [],
  options: { excerptLength?: number } = {},
): Promise<ParsedJournalContent> {
  const excerptLength = options.excerptLength ?? 1000
  const normalizedBody = body.replace(/\r\n/g, '\n').trim()
  const bodySections = splitBodySections(normalizedBody)

  if (bodySections.length > 0) {
    const introMarkdown = extractIntroMarkdown(normalizedBody, bodySections[0])
    const introHtml = introMarkdown ? await renderMarkdown(introMarkdown) : ''
    const parsedEntries = (
      await Promise.all(
        bodySections.map(async (section) => parseBodySection(section, excerptLength)),
      )
    ).sort((a, b) => b.date.getTime() - a.date.getTime())

    return {
      introMarkdown,
      introHtml,
      entries: parsedEntries,
      usesBodyEntries: true,
    }
  }

  const parsedLegacyEntries = (
    await Promise.all(
      legacyEntries.map(async (entry) => {
        const contentMarkdown = entry.summary.trim()
        return {
          title: entry.title,
          date: entry.date,
          location: entry.location,
          mileage: entry.mileage,
          contentMarkdown,
          contentHtml: await renderMarkdown(contentMarkdown),
          excerpt: summarizeMarkdown(contentMarkdown, excerptLength),
        }
      }),
    )
  ).sort((a, b) => b.date.getTime() - a.date.getTime())

  const introHtml = normalizedBody ? await renderMarkdown(normalizedBody) : ''

  return {
    introMarkdown: normalizedBody,
    introHtml,
    entries: parsedLegacyEntries,
    usesBodyEntries: false,
  }
}

function splitBodySections(body: string): BodySection[] {
  const matches = [...body.matchAll(/^##\s+(.+)$/gm)]
  if (matches.length === 0) {
    return []
  }

  return matches
    .map((match, index) => {
      const start = match.index ?? 0
      const nextStart = matches[index + 1]?.index ?? body.length
      const rawSection = body.slice(start, nextStart).trim()
      const lines = rawSection.split('\n')
      const heading = lines.shift()?.replace(/^##\s+/, '').trim() ?? ''
      return {
        heading,
        markdown: lines.join('\n').trim(),
      }
    })
    .filter((section) => DATE_PREFIX_PATTERN.test(section.heading))
}

function extractIntroMarkdown(body: string, firstSection: BodySection): string {
  const marker = `## ${firstSection.heading}`
  const index = body.indexOf(marker)
  if (index === -1) {
    return ''
  }

  return body.slice(0, index).trim()
}

async function parseBodySection(
  section: BodySection,
  excerptLength: number,
): Promise<ParsedJournalEntry> {
  const { date, title } = parseHeading(section.heading)
  const { location, mileage, contentMarkdown } = extractSectionMetadata(section.markdown)
  const contentHtml = await renderMarkdown(contentMarkdown)

  return {
    title,
    date,
    location,
    mileage,
    contentMarkdown,
    contentHtml,
    excerpt: summarizeMarkdown(contentMarkdown, excerptLength),
  }
}

function parseHeading(heading: string): { date: Date; title?: string } {
  const match = heading.match(DATE_PREFIX_PATTERN)
  if (!match) {
    throw new Error(`Invalid journal entry heading: "${heading}"`)
  }

  return {
    date: new Date(`${match[1]}T00:00:00`),
    title: match[2]?.trim() || undefined,
  }
}

function extractSectionMetadata(markdown: string): {
  location?: string
  mileage?: string
  contentMarkdown: string
} {
  const lines = markdown.split('\n')
  let lineIndex = 0
  let location: string | undefined
  let mileage: string | undefined

  while (lineIndex < lines.length) {
    const currentLine = lines[lineIndex].trim()

    if (!currentLine) {
      lineIndex += 1
      continue
    }

    const locationMatch = currentLine.match(LOCATION_PATTERN)
    if (locationMatch) {
      location = locationMatch[1].trim()
      lineIndex += 1
      continue
    }

    const mileageMatch = currentLine.match(MILEAGE_PATTERN)
    if (mileageMatch) {
      mileage = mileageMatch[1].trim()
      lineIndex += 1
      continue
    }

    break
  }

  const contentMarkdown = lines.slice(lineIndex).join('\n').trim()

  return {
    location,
    mileage,
    contentMarkdown,
  }
}

async function renderMarkdown(markdown: string): Promise<string> {
  if (!markdown.trim()) {
    return ''
  }

  return await marked.parse(markdown)
}

function summarizeMarkdown(markdown: string, maxLength = 220): string {
  const plainText = markdown
    .replace(/!\[([^\]]*)\]\([^)]+\)/g, '$1')
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    .replace(/[`*_>#-]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()

  if (plainText.length <= maxLength) {
    return plainText
  }

  const truncated = plainText.slice(0, maxLength).trim()
  const lastSpace = truncated.lastIndexOf(' ')
  return `${truncated.slice(0, lastSpace > 0 ? lastSpace : truncated.length)}...`
}
