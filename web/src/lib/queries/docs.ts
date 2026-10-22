import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api, seg } from '../api'
import type { DocMeta, DocPage } from '../types'
import { qk } from './keys'

const fetchDoc = (slug: string) => api.get<DocPage>(`/api/docs/${seg(slug)}`)

export const docsQuery = () => ({ queryKey: qk.docs.list, queryFn: () => api.get<DocMeta[]>('/api/docs'), staleTime: 5 * 60_000 })
export const docQuery = (slug: string) => ({ queryKey: qk.docs.page(slug), queryFn: () => fetchDoc(slug), staleTime: 5 * 60_000 })
export function useDocs() {
  return useQuery(docsQuery())
}
export function useDoc(slug: string | undefined) {
  return useQuery({ ...docQuery(slug || ''), enabled: !!slug })
}
/** Every doc page with its markdown, in one request (full-text search). Only enabled while searching; the
 *  pages are also seeded into their own cache entries (opening a hit is instant). */
export function useAllDocs(enabled: boolean) {
  const qc = useQueryClient()
  return useQuery({
    queryKey: qk.docs.full,
    queryFn: async () => {
      const pages = await api.get<(DocMeta & DocPage)[]>('/api/docs', { full: 1 })
      for (const p of pages) qc.setQueryData<DocPage>(qk.docs.page(p.slug), { slug: p.slug, title: p.title, markdown: p.markdown })
      return pages
    },
    enabled,
    staleTime: 5 * 60_000,
  })
}
