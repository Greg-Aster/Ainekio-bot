/// <reference types="mdast" />
import { h } from 'hastscript'

/**
 * Creates a Bio Card component.
 *
 * @param {Object} properties - The properties of the component.
 * @param {string} properties.title - The title of the bio card.
 * @param {string} properties.href - The link to the expanded resume or bio.
 * @param {import('mdast').RootContent[]} children - The children elements of the component.
 * @returns {import('mdast').Parent} The created Bio Card component.
 */
export function BioCardComponent(properties, children) {
  if (Array.isArray(children) && children.length !== 0)
    return h('div', { class: 'hidden' }, [
      'Invalid directive. ("bio" directive must be leaf type "::bio{title="Your Title", href="your-link"}")',
    ])

  if (!properties.title || !properties.href)
    return h(
      'div',
      { class: 'hidden' },
      'Invalid properties. ("title" and "href" attributes are required)',
    )

  const title = properties.title
  const href = properties.href
  const cardUuid = `BC${Math.random().toString(36).slice(-6)}` // Collisions are not important

  const nTitle = h(`div`, { class: 'bc-titlebar' }, [
    h('div', { class: 'bc-titlebar-left' }, [
      h('div', { class: 'bc-title' }, title),
    ]),
  ])

  const nDescription = h(
    `div#${cardUuid}-description`,
    { class: 'bc-description' },
    'Click to view the expanded resume or bio.',
  )

  return h(
    `a#${cardUuid}-card`,
    {
      class: 'card-bio no-styling',
      href: href,
      target: '_blank',
    },
    [
      nTitle,
      nDescription,
    ],
  )
}
