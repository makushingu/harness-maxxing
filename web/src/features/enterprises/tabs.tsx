// The tabs of an enterprise's page, in order. The first is the home (the address without a tab, /enterprises/<id>);
// the others are /enterprises/<id>/<id of the tab>. To add a tab, add an entry here: nothing else has to change.
import type * as React from 'react'
import type { TKey } from '@/i18n'
import type { Enterprise } from '@/lib/types'
import { EnterpriseSettings } from './EnterpriseSettings'
import { OrgChart } from './OrgChart'

export type EnterpriseTab = {
  /** the tab's address segment; the home tab's id is not shown in the address */
  id: string
  label: TKey
  render: (e: Enterprise) => React.ReactNode
}

export const ENTERPRISE_TABS: EnterpriseTab[] = [
  { id: 'chart', label: 'ent.tab.chart', render: (e) => <OrgChart enterprise={e} /> },
  { id: 'settings', label: 'ent.tab.settings', render: (e) => <EnterpriseSettings enterprise={e} /> },
]
