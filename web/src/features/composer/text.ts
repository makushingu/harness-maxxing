// Text helpers shared by the message boxes.

/** `heard` (a dictation) put at the caret of `el` in `text`, with a space on each side when needed. */
export function insertAtCaret(el: HTMLTextAreaElement | null, text: string, heard: string): { text: string; caret: number } {
  const start = el ? el.selectionStart : text.length
  const end = el ? el.selectionEnd : text.length
  const before = text.slice(0, start)
  const after = text.slice(end)
  const ins = (before && !/\s$/.test(before) ? ' ' : '') + heard + (after && !/^\s/.test(after) ? ' ' : '')
  return { text: before + ins + after, caret: before.length + ins.length }
}
