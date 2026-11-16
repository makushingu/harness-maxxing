// "Copy the text" of the file shown (viewer, FilePreview, Files page). A file drawn from its source (Markdown,
// HTML) and an office document give two choices: the source as it is, or the words alone (plain text). Code, text
// and CSV have one text; a workbook gives its cells, a PDF the words the server reads in it.
import { useQueryClient } from '@tanstack/react-query'
import { Code2, Copy, TextInitial, type LucideIcon } from 'lucide-react'
import { Button, DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger, toast, Tooltip } from '@/components/ui'
import { api } from '@/lib/api'
import { fileDocQuery } from '@/lib/queries/files'
import { qk } from '@/lib/queries/keys'
import type { FileContent } from '@/lib/types'
import { copyText, copyTextLater } from '@/lib/utils'
import { useT } from '@/i18n'
import { basename, isSheets, isTextual, type FileKind } from './kinds'

export type CopyChoice = { id: 'source' | 'plain'; label: string; icon: LucideIcon; text: () => string | Promise<string> }

type Props = {
  path: string
  kind: FileKind
  /** The file's text when the page already has it (else it is asked on the click). */
  text?: string
}

const plain = () => import('./plainText')

/** What can be copied from this file: nothing (a picture, an archive, a text not read yet), one text, or two. */
export function useCopyChoices({ path, kind, text }: Props): CopyChoice[] {
  const t = useT()
  const qc = useQueryClient()
  const cut = () => toast.info(t('ctext.truncated'))
  const one = (get: CopyChoice['text']): CopyChoice[] => [{ id: 'source', label: t('ctext.copy'), icon: Copy, text: get }]
  const two = (label: string, source: () => string | Promise<string>, words: (src: string) => Promise<string>): CopyChoice[] => [
    { id: 'source', label, icon: Code2, text: source },
    { id: 'plain', label: t('ctext.plain'), icon: TextInitial, text: async () => words(await source()) },
  ]
  if (kind === 'pdf')
    return one(async () => {
      const r = await api.get<{ text: string; truncated: boolean }>('/api/files/pdf/text', { path })
      if (r.truncated && r.text) cut()
      return r.text
    })
  if (kind === 'document') {
    const doc = async () => {
      const d = await qc.fetchQuery(fileDocQuery(path))
      if (d.truncated) cut()
      return d
    }
    if (isSheets(basename(path)))
      return one(async () => {
        const [d, m] = await Promise.all([doc(), plain()])
        return d.type === 'sheets' ? m.sheetsToText(d.sheets) : ''
      })
    return two(
      t('ctext.markdown'),
      async () => {
        const d = await doc()
        return d.type === 'sheets' ? '' : d.markdown
      },
      async (md) => (await plain()).markdownToText(md),
    )
  }
  // The page of an HTML file is shown without reading its source: asked on the click.
  if (!isTextual(kind) || (text === undefined && kind !== 'html')) return []
  const source = () =>
    text ?? qc.fetchQuery({ queryKey: qk.files.read(path), queryFn: () => api.get<FileContent>('/api/files/read', { path }), staleTime: 30_000 }).then((d) => d.content)
  if (kind === 'markdown') return two(t('ctext.source'), source, async (md) => (await plain()).markdownToText(md))
  if (kind === 'html') return two(t('ctext.source'), source, async (html) => (await plain()).htmlToText(html))
  return one(source)
}

/** Copies a choice and says what happened (a scan has no text, a file may have gone). */
function useCopy() {
  const t = useT()
  return async (c: CopyChoice) => {
    let empty = false
    const filled = (s: string) => {
      if (s.trim()) return s
      empty = true
      throw new Error('empty')
    }
    let ok = false
    try {
      const got = c.text()
      ok = typeof got === 'string' ? await copyText(filled(got)) : await copyTextLater(got.then(filled))
    } catch {
      ok = false
    }
    if (ok) toast.success(t('ctext.copied'))
    else toast.error(t(empty ? 'ctext.empty' : 'ctext.failed'))
  }
}

/** The choices as the rows of a menu (the "more" menu of a phone, the menu of the Files page). */
export function CopyTextItems(props: Props) {
  const list = useCopyChoices(props)
  const copy = useCopy()
  return (
    <>
      {list.map((c) => (
        <DropdownMenuItem key={c.id} onSelect={() => void copy(c)} data-testid={`copy-text-${c.id}`}>
          <c.icon />
          {c.label}
        </DropdownMenuItem>
      ))}
    </>
  )
}

/** The button of a title bar: copies at once when the file has one text, else opens the two choices. */
export function CopyTextButton({ className, ...props }: Props & { className?: string }) {
  const t = useT()
  const list = useCopyChoices(props)
  const copy = useCopy()
  if (!list.length) return null
  if (list.length === 1)
    return (
      <Tooltip content={list[0].label}>
        <Button variant="ghost" size="icon-sm" onClick={() => void copy(list[0])} aria-label={list[0].label} className={className} data-testid="copy-text">
          <Copy />
        </Button>
      </Tooltip>
    )
  return (
    <DropdownMenu>
      <Tooltip content={t('ctext.copy')}>
        <DropdownMenuTrigger asChild>
          <Button variant="ghost" size="icon-sm" aria-label={t('ctext.copy')} className={className} data-testid="copy-text">
            <Copy />
          </Button>
        </DropdownMenuTrigger>
      </Tooltip>
      <DropdownMenuContent align="end" className="w-56">
        <CopyTextItems {...props} />
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
