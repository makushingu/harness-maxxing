// Week view: the open tasks in columns by due date (overdue, today, the next 6 days, later, no date). Dropping a card
// on a day sets its due date; "overdue" and "later" are only sources (their date is not one day).
import type { Task } from '@/lib/types'
import type { TFn } from '@/i18n'
import { addDays, byOrder, daysBetween } from './model'
import type { BoardColumn } from './Board'

const cmp = (a: Task, b: Task) => b.priority - a.priority || Number(b.status === 'doing') - Number(a.status === 'doing') || byOrder(a, b)

export function weekColumns(
  tasks: Task[],
  today: string,
  lang: string,
  t: TFn,
  onAdd?: (due: string | null, text: string) => Promise<unknown>,
): BoardColumn[] {
  const open = tasks.filter((x) => x.status !== 'done')
  const day = new Intl.DateTimeFormat(lang, { weekday: 'long', timeZone: 'UTC' })
  const short = new Intl.DateTimeFormat(lang, { day: 'numeric', month: 'short', timeZone: 'UTC' })
  const cols: BoardColumn[] = [
    { id: 'overdue', label: t('tasks.group.overdue'), tone: 'danger', droppable: false, tasks: open.filter((x) => x.due && x.due < today).sort((a, b) => a.due!.localeCompare(b.due!) || cmp(a, b)) },
  ]
  for (let i = 0; i < 7; i++) {
    const d = addDays(today, i)
    const date = new Date(`${d}T12:00:00Z`)
    const name = i === 0 ? t('tasks.due.today') : i === 1 ? t('tasks.due.tomorrow') : day.format(date)
    cols.push({
      id: d,
      label: name.charAt(0).toUpperCase() + name.slice(1),
      sub: short.format(date),
      tasks: open.filter((x) => x.due === d).sort(cmp),
      onAdd: onAdd ? (text) => onAdd(d, text) : undefined,
    })
  }
  cols.push({ id: 'later', label: t('tasks.group.later'), droppable: false, tasks: open.filter((x) => x.due && daysBetween(today, x.due) > 6).sort((a, b) => a.due!.localeCompare(b.due!) || cmp(a, b)) })
  cols.push({ id: 'none', label: t('tasks.group.noDate'), tasks: open.filter((x) => !x.due).sort(cmp), onAdd: onAdd ? (text) => onAdd(null, text) : undefined })
  return cols
}

/** Due date a week column gives to a card dropped on it (undefined = leave the date). */
export function weekDropDue(column: string): string | null | undefined {
  if (column === 'none') return null
  if (/^\d{4}-\d{2}-\d{2}$/.test(column)) return column
  return undefined
}
