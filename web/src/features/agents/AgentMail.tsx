// The "E-mail" section of an agent's settings: the mailboxes of the E-mail page it may use (agent.json `mail`, none by
// default). Per mailbox: what it may do, the senders it deals with (checked by the provider; it also writes only to
// them), whether its messages wait for the owner's OK, and "start on each new mail". Every change saves at once (the
// texts of the trigger when the field is left). The password stays in the Keys vault: the agent never sees it.
import * as React from 'react'
import { Link } from 'react-router'
import { Mail, Plus, Trash2 } from 'lucide-react'
import { useT } from '@/i18n'
import { useMailAccounts, useMailFolders, usePatchAgent, useSettings } from '@/lib/queries'
import type { AgentDetail, MailAccount, MailApproveSend, MailGrant, MailRight, MailTrigger } from '@/lib/types'
import { Button, Checkbox, confirm, FormField, Input, Select, Sensitive, Switch, Textarea } from '@/components/ui'
import { Callout } from '@/features/common'
import { folderLabel } from '@/features/mail/shared'
import { ListEditor } from './AgentSettings'

const RIGHTS: MailRight[] = ['read', 'draft', 'move', 'mark', 'send']
const APPROVE: MailApproveSend[] = ['always', 'new', 'never']
const NEW_TRIGGER: MailTrigger = { enabled: true, folder: 'INBOX', subject: '', senders: [], prompt: '' }

export function AgentMail({ agent: a }: { agent: AgentDetail }) {
  const t = useT()
  const { data: settings } = useSettings()
  const on = !!settings?.mail_page
  const { data: accounts, isLoading } = useMailAccounts(on)
  const patch = usePatchAgent()
  const grants = a.mail || []
  const save = (list: MailGrant[]) => patch.mutate({ path: a.path, mail: list })
  const setOne = (acc: string, g: Partial<MailGrant>) => save(grants.map((x) => (x.account === acc ? { ...x, ...g } : x)))
  const free = (accounts || []).filter((x) => !grants.some((g) => g.account === x.id))
  const [pick, setPick] = React.useState('')

  return (
    <div className="grid grid-cols-[minmax(0,1fr)] gap-4" data-testid="agent-mail">
      <p className="text-[13px] text-muted-foreground">{t('agents.mail.none')}</p>
      {settings && !on ? (
        <Callout tone="info">
          {t('agents.mail.off')}{' '}
          <Link to="/settings/features" className="text-primary underline">
            {t('agents.mail.openFeatures')}
          </Link>
        </Callout>
      ) : (
        <>
          {grants.map((g) => (
            <GrantCard
              key={g.account}
              grant={g}
              account={(accounts || []).find((x) => x.id === g.account)}
              onChange={(v) => setOne(g.account, v)}
              onRemove={async () => {
                if (await confirm({ title: t('agents.mail.removeTitle'), description: t('agents.mail.removeDesc'), destructive: true, confirmText: t('common.remove') }))
                  save(grants.filter((x) => x.account !== g.account))
              }}
            />
          ))}
          {!isLoading && accounts && !accounts.length ? (
            <Callout tone="info">
              {t('agents.mail.noBox')}{' '}
              <Link to="/mail" className="text-primary underline">
                {t('agents.mail.openMail')}
              </Link>
            </Callout>
          ) : (
            !!free.length && (
              <div className="flex gap-2">
                <Select
                  className="h-8 min-w-0 flex-1"
                  value={pick || undefined}
                  onValueChange={setPick}
                  placeholder={t('agents.mail.pick')}
                  aria-label={t('agents.mail.pick')}
                  options={free.map((x) => ({ value: x.id, label: x.label ? `${x.label} (${x.address})` : x.address }))}
                />
                <Button
                  size="sm"
                  variant="outline"
                  disabled={!pick}
                  loading={patch.isPending}
                  onClick={() => (save([...grants, { account: pick, rights: ['read', 'draft'], senders: [], approve_send: 'always', trigger: null }]), setPick(''))}
                  data-testid="agent-mail-add"
                >
                  <Plus /> {t('agents.mail.add')}
                </Button>
              </div>
            )
          )}
          <p className="text-xs text-muted-foreground">{t('agents.mail.password')}</p>
        </>
      )}
    </div>
  )
}

function GrantCard({ grant: g, account, onChange, onRemove }: { grant: MailGrant; account?: MailAccount; onChange: (g: Partial<MailGrant>) => void; onRemove: () => void }) {
  const t = useT()
  const tr = g.trigger
  const watching = !!tr?.enabled
  const folders = useMailFolders(watching && account ? g.account : null)
  // the texts of the trigger save when the field is left
  const [subject, setSubject] = React.useState(tr?.subject || '')
  const [prompt, setPrompt] = React.useState(tr?.prompt || '')
  React.useEffect(() => {
    setSubject(tr?.subject || '')
    setPrompt(tr?.prompt || '')
  }, [tr?.subject, tr?.prompt])
  const setTrigger = (v: Partial<MailTrigger>) => onChange({ trigger: { ...NEW_TRIGGER, ...tr, ...v } })
  const toggle = (r: MailRight, v: boolean) => onChange({ rights: RIGHTS.filter((x) => (x === r ? v : g.rights.includes(x))) })
  const folderOptions = (folders.data || []).map((f) => ({ value: f.name, label: folderLabel(f, t) }))
  if (tr?.folder && !folderOptions.some((o) => o.value === tr.folder)) folderOptions.unshift({ value: tr.folder, label: tr.folder })

  return (
    <div className="grid grid-cols-[minmax(0,1fr)] gap-4 rounded-xl border p-3" data-testid="agent-mail-grant">
      <div className="flex items-center gap-2">
        <Mail className="size-4 shrink-0 text-primary" />
        <span className="min-w-0 flex-1 truncate text-sm font-medium">
          <Sensitive length={10}>{account ? account.address : g.account}</Sensitive>
        </span>
        {!account && <span className="text-xs text-warning">{t('agents.mail.gone')}</span>}
        <Button variant="ghost" size="icon-sm" onClick={onRemove} aria-label={t('agents.mail.remove')}>
          <Trash2 />
        </Button>
      </div>

      <fieldset className="grid gap-2">
        <legend className="mb-2 text-sm font-medium">{t('agents.mail.rights')}</legend>
        {RIGHTS.map((r) => {
          const id = `ag-mail-${g.account}-${r}`
          return (
            <div key={r} className="flex items-start gap-2.5">
              <Checkbox id={id} checked={g.rights.includes(r)} onCheckedChange={(v) => toggle(r, !!v)} className="mt-0.5" />
              <label htmlFor={id} className="grid cursor-pointer gap-0.5">
                <span className="text-sm">{t(`agents.mail.right.${r}`)}</span>
                <span className="text-xs text-muted-foreground">{t(`agents.mail.right.${r}Desc`)}</span>
              </label>
            </div>
          )
        })}
      </fieldset>

      {g.rights.includes('send') && (
        <FormField label={t('agents.mail.approve')}>
          <Select value={g.approve_send} onValueChange={(v) => onChange({ approve_send: v as MailApproveSend })} options={APPROVE.map((x) => ({ value: x, label: t(`agents.mail.approve.${x}`) }))} />
        </FormField>
      )}

      <div className="grid gap-2">
        <div className="grid gap-0.5">
          <span className="text-sm font-medium">{t('agents.mail.senders')}</span>
          <span className="text-xs text-muted-foreground">{t('agents.mail.sendersDesc')}</span>
        </div>
        <ListEditor
          value={g.senders}
          onChange={(l, saved) => (onChange({ senders: l }), saved?.())}
          placeholder="*@stripe.com, client@example.com"
          empty={t('agents.mail.sendersAll')}
          error={null}
          testid="agent-mail-senders"
        />
        {g.senders.length > 0 && account?.sender_check && !['auto', 'owner'].includes(account.sender_check.state) && (
          <p className="text-xs text-warning">{t('agents.mail.sendersUnchecked', { address: account.address })}</p>
        )}
      </div>

      <div className="grid gap-3 border-t pt-3">
        <div className="flex items-start gap-3">
          <label htmlFor={`ag-mail-${g.account}-trigger`} className="grid min-w-0 flex-1 cursor-pointer gap-0.5">
            <span className="text-sm font-medium">{t('agents.mail.trigger')}</span>
            <span className="text-xs text-muted-foreground">{t('agents.mail.triggerDesc')}</span>
          </label>
          <Switch id={`ag-mail-${g.account}-trigger`} checked={watching} onCheckedChange={(v) => setTrigger({ enabled: v })} data-testid="agent-mail-trigger" />
        </div>
        {watching && (
          <>
            <div className="grid items-start gap-3 sm:grid-cols-2">
              <FormField label={t('agents.mail.folder')}>
                <Select value={tr?.folder || 'INBOX'} onValueChange={(v) => setTrigger({ folder: v })} options={folderOptions.length ? folderOptions : [{ value: 'INBOX', label: 'INBOX' }]} />
              </FormField>
              <FormField label={t('agents.mail.subject')} hint={t('agents.mail.subjectHint')}>
                <Input value={subject} onChange={(e) => setSubject(e.target.value)} onBlur={() => subject.trim() !== (tr?.subject || '') && setTrigger({ subject: subject.trim() })} />
              </FormField>
            </div>
            <FormField label={t('agents.trigger.prompt')} hint={t('agents.mail.promptHint')}>
              <Textarea minRows={2} maxRows={8} value={prompt} onChange={(e) => setPrompt(e.target.value)} onBlur={() => prompt.trim() !== (tr?.prompt || '') && setTrigger({ prompt: prompt.trim() })} />
            </FormField>
          </>
        )}
      </div>
    </div>
  )
}
