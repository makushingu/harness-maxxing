// "New session…" in the menu of a repository, a branch or a commit (Git page, ```git blocks): the session opens in
// the topic the user picks, with what was clicked already typed in its composer (the repository and where its clone
// is, the branch or the commit). Nothing is sent: the user writes what to do.
import * as React from 'react'
import { useNavigate } from 'react-router'
import { useCreateSession, useWorkspace } from '@/lib/queries'
import { useT } from '@/i18n'
import { Button, Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, Label } from '@/components/ui'
import { Combobox } from '@/components/ui/combobox'
import { prefillDraft } from '@/pages/sessions/store'

export type GitSessionTarget = {
  /** "owner/name" on GitHub */
  github?: string | null
  /** its clones on this server */
  clones?: string[]
  branch?: string
  sha?: string
  subject?: string
}

const stop = (e: React.SyntheticEvent) => e.stopPropagation()

const TOPIC_KEY = 'mx-git-topic'
const lastTopic = () => {
  try {
    return localStorage.getItem(TOPIC_KEY) || ''
  } catch {
    return ''
  }
}

export function GitSessionDialog({ target, onClose }: { target: GitSessionTarget; onClose: () => void }) {
  const t = useT()
  const navigate = useNavigate()
  const { data: ws } = useWorkspace()
  const create = useCreateSession()
  const topics = React.useMemo(() => (ws?.projects || []).flatMap((p) => p.topics.map((tp) => ({ value: tp.path, label: `${p.name}/${tp.name}` }))), [ws])
  const [picked, setPicked] = React.useState('')
  const clones = target.clones || []
  // the topic the clone is in, else the one picked last time, else the inbox
  const topic =
    picked ||
    (ws && topics.find((x) => clones.some((c) => `${c}/`.startsWith(`${ws.root}/${x.value}/`)))?.value) ||
    topics.find((x) => x.value === lastTopic())?.value ||
    topics.find((x) => x.value.endsWith('/topics/inbox'))?.value ||
    topics[0]?.value ||
    ''
  const name = target.github || clones[0]?.split('/').pop() || ''
  const repo = clones.length ? t('git.session.cloned', { repo: name, path: clones.join(', ') }) : t('git.session.remote', { repo: name })
  const draft = target.sha
    ? t('git.session.commit', { repo, sha: target.sha.slice(0, 10), subject: target.subject || '' })
    : target.branch
      ? t('git.session.branch', { repo, branch: target.branch })
      : t('git.session.repo', { repo })
  const submit = () =>
    create.mutate(
      { path: topic, title: [name.split('/').pop(), target.branch || target.sha?.slice(0, 7)].filter(Boolean).join(' · ').slice(0, 60) },
      {
        onSuccess: (s) => {
          try {
            localStorage.setItem(TOPIC_KEY, topic)
          } catch {
            /* private mode */
          }
          prefillDraft(s.id, draft)
          onClose()
          navigate(`/sessions/${s.id}`)
        },
      },
    )
  // A portal, but React events still bubble to where it is rendered (a row of the list, a message of the chat with its
  // own menu and long press): they stop here.
  return (
    <div className="contents" onClick={stop} onDoubleClick={stop} onContextMenu={stop} onKeyDown={stop} onPointerDown={stop} onMouseDown={stop} onTouchStart={stop} onTouchMove={stop} onTouchEnd={stop} onTouchCancel={stop}>
      <Dialog open onOpenChange={(o) => !o && onClose()}>
        <DialogContent className="md:max-w-lg" data-testid="git-session-dialog">
          <DialogHeader>
            <DialogTitle>{t('git.session.title')}</DialogTitle>
            <DialogDescription>{t('git.session.desc')}</DialogDescription>
          </DialogHeader>
          <p className="rounded-md border bg-fill-1 px-3 py-2 text-[13px] break-words text-muted-foreground" data-testid="git-session-draft">
            {draft}
          </p>
          <div className="flex flex-col gap-1.5">
            <Label>{t('git.session.topic')}</Label>
            <Combobox value={topic} onChange={setPicked} options={topics} placeholder={t('git.session.pickTopic')} searchPlaceholder={t('git.session.searchTopic')} aria-label={t('git.session.topic')} />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={onClose}>
              {t('common.cancel')}
            </Button>
            <Button onClick={submit} disabled={!topic} loading={create.isPending} data-testid="git-session-create">
              {t('git.session.create')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
