/** The longest code block that gets colours. highlight.js runs on the page's thread and some grammars are worse than
 * quadratic on hostile text: markdown with unclosed links (10 KB = 5 s, 20 KB = 44 s frozen), java / ini /
 * typescript on one long run of a character (20 KB = 2 s). A longer block shows as plain text, like an unknown language. */
export const HIGHLIGHT_MAX = 20_000
export const MARKDOWN_HIGHLIGHT_MAX = 3_000
const MARKDOWN = new Set(['markdown', 'md', 'mkdown', 'mkd'])

export const canHighlight = (lang: string, size: number): boolean =>
  size <= (MARKDOWN.has(lang.toLowerCase()) ? MARKDOWN_HIGHLIGHT_MAX : HIGHLIGHT_MAX)
