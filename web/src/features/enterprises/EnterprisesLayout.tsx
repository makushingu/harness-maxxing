// The Enterprises page (/enterprises/*, Settings -> Features -> enterprises_page, needs Agents):
//   /enterprises                      -> the enterprises
//   /enterprises/<id>                 -> one enterprise: its org chart (the first tab, see tabs.tsx)
//   /enterprises/<id>/<tab>           -> another tab of it (settings, ...)
// ?pos=<position id> opens a position's panel on the chart.
import { Route, Routes } from 'react-router'
import { PreviewProvider } from '@/pages/sessions/FilePreview'
import EnterprisePage from './EnterprisePage'
import { EnterprisesList } from './EnterprisesList'
import { EnterprisesOff, useEnterprisesOn } from './parts'

export default function EnterprisesLayout() {
  const on = useEnterprisesOn()
  if (on === false) return <EnterprisesOff />
  // PreviewProvider: the conversation of a position is the agents' one, which previews files
  return (
    <PreviewProvider>
      <Routes>
        <Route index element={<EnterprisesList />} />
        <Route path=":id" element={<EnterprisePage key="home" />} />
        <Route path=":id/:tab" element={<EnterprisePage key="tab" />} />
      </Routes>
    </PreviewProvider>
  )
}
