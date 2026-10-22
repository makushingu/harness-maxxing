import { useQuery } from '@tanstack/react-query'
import { api } from '../api'
import type { BackupConfigBody, BackupConfigResult, BackupRestoreResult, BackupRun, BackupRunResult, BackupSettingsBody, BackupStatus, Ok } from '../types'
import { qk } from './keys'
import { useMut } from './util'

export const backupQuery = () => ({ queryKey: qk.backup.status, queryFn: () => api.get<BackupStatus>('/api/backup') })
export function useBackup() {
  return useQuery(backupQuery())
}
export function useBackupHistory() {
  return useQuery({ queryKey: qk.backup.history, queryFn: () => api.get<BackupRun[]>('/api/backup/history') })
}
const inv = [qk.backup.all, qk.onboarding, qk.health] as const
export function useBackupConfig() {
  return useMut((b: BackupConfigBody) => api.post<BackupConfigResult>('/api/backup/config', b), { invalidate: inv, errorToast: false })
}
export function useBackupSettings() {
  return useMut((b: BackupSettingsBody) => api.put<Ok>('/api/backup/settings', b), { invalidate: inv })
}
export function useBackupRun() {
  return useMut(() => api.post<BackupRunResult>('/api/backup/run'), { invalidate: inv, errorToast: false })
}
export function useBackupRestore() {
  return useMut((ref?: string) => api.post<BackupRestoreResult>('/api/backup/restore', ref ? { ref } : {}), { invalidate: inv })
}
export function useBackupForget() {
  return useMut(() => api.del<Ok>('/api/backup'), { invalidate: inv })
}
