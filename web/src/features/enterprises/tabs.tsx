// The tabs of an enterprise's page, in order. The first is the home (the address without a tab, /enterprises/<id>);
// the others are /enterprises/<id>/<id of the tab>. To add a tab, add an entry here: nothing else has to change.
import type * as React from 'react'
import type { TKey } from '@/i18n'
import type { Enterprise } from '@/lib/types'
import { Decisions } from './Decisions'
import { EnterpriseSettings } from './EnterpriseSettings'
import { OrgChart } from './OrgChart'
import { Overview } from './Overview'
import { ProfileTab } from './ProfileTab'
import { Reports } from './Reports'

export type EnterpriseTab = {
  /** the tab's address segment; the home tab's id is not shown in the address */
  id: string
  label: TKey
  render: (e: Enterprise) => React.ReactNode
}

export const ENTERPRISE_TABS: EnterpriseTab[] = [
  { id: 'chart', label: 'ent.tab.chart', render: (e) => <OrgChart enterprise={e} /> },
  { id: 'overview', label: 'ent.tab.overview', render: (e) => <Overview enterprise={e} /> },
  { id: 'decisions', label: 'ent.tab.decisions', render: (e) => <Decisions enterprise={e} /> },
  { id: 'reports', label: 'ent.tab.reports', render: (e) => <Reports enterprise={e} /> },
  { id: 'profile', label: 'ent.tab.profile', render: (e) => <ProfileTab enterprise={e} /> },
  { id: 'settings', label: 'ent.tab.settings', render: (e) => <EnterpriseSettings enterprise={e} /> },
]
