// "Revert to before this message" (lot 2): every repository the turn changed goes back to its photo from before
// it (files only); the toast offers "Restore" for 10 s (server: POST /api/sessions/{id}/revert, /api/code/undo).
import * as React from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { toast } from '@/components/ui'
import { errorMessage, isApiError } from '@/lib/api'
import { useT } from '@/i18n'
import { codeApi } from './api'

export function useRevert(sid: string | undefined) {
  const t = useT()
  const qc = useQueryClient()
  return React.useCallback(
    async (n: number) => {
      if (!sid) return
      const refresh = () => void qc.invalidateQueries({ queryKey: ['code'] })
      try {
        const out = await codeApi.revert(sid, n)
        refresh()
        const back = out.repos.map((r) => ({ root: r.root, undo: r.undo }))
        toast.action(t('sessions.revertDone'), out.repos.some((r) => r.commits_kept) ? t('sessions.revertCommits') : undefined, {
          label: t('sessions.revertRestore'),
          onClick: () => void codeApi.undo(back).then(refresh, (e) => toast.error(t('sessions.revertFailed'), errorMessage(e))),
        }, 10_000)
      } catch (e) {
        if (isApiError(e, 'running')) toast.error(t('sessions.revertBusy'))
        else toast.error(t('sessions.revertFailed'), errorMessage(e))
      }
    },
    [sid, t, qc],
  )
}
