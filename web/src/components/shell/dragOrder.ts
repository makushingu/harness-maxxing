// Reordering a short list by native drag and drop (sidebar pages, pinned extension pages): the dragged row moves as
// the pointer passes over the others, the new order is committed on drop. Each list has its own `scope`: a row
// dragged from another list is not accepted (extension pages never land among the pages, and the reverse).
import * as React from 'react'

export function useDragOrder(ids: string[], commit: (ids: string[]) => void, scope: string) {
  const type = `application/x-mx-${scope}`
  const [live, setLive] = React.useState<string[] | null>(null)
  const liveRef = React.useRef<string[] | null>(null)
  const dragged = React.useRef<string | null>(null)
  const update = (l: string[] | null) => {
    liveRef.current = l
    setLive(l)
  }
  const props = (id: string) => ({
    draggable: true,
    'data-dragging': live !== null && dragged.current === id ? '' : undefined,
    onDragStart: (e: React.DragEvent) => {
      dragged.current = id
      e.dataTransfer.effectAllowed = 'move'
      e.dataTransfer.setData(type, id)
      update(ids)
    },
    onDragOver: (e: React.DragEvent) => {
      const from = dragged.current
      if (!from || !e.dataTransfer.types.includes(type)) return // another list (or a file): not a drop target
      e.preventDefault()
      e.dataTransfer.dropEffect = 'move'
      if (from === id) return
      const r = e.currentTarget.getBoundingClientRect()
      const cur = liveRef.current ?? ids
      const l = cur.filter((x) => x !== from)
      l.splice(l.indexOf(id) + (e.clientY > r.top + r.height / 2 ? 1 : 0), 0, from)
      if (l.join('\n') !== cur.join('\n')) update(l)
    },
    onDrop: (e: React.DragEvent) => {
      if (dragged.current && e.dataTransfer.types.includes(type)) e.preventDefault()
    },
    onDragEnd: (e: React.DragEvent) => {
      const l = liveRef.current?.filter((x) => ids.includes(x))
      dragged.current = null
      update(null)
      if (e.dataTransfer.dropEffect === 'none') return // Escape, or dropped outside the list: nothing changes
      if (l && l.join('\n') !== ids.join('\n')) commit(l)
    },
  })
  return { order: live ?? ids, props }
}
