// Emoji search in the interface language, with English as a fallback: the picker shows the labels and categories
// of the interface language, and each emoji also answers to its English name and tags, and to its words without
// accents ("coeur" finds "cœur"). Both data sets come from frimousse's own resolver (cached in localStorage,
// emojis the device cannot draw filtered out); the merged result is kept in memory by frimousse.
import { defaultEmojiDataResolver } from 'frimousse'
import { fold } from '@/lib/utils'

type Resolver = typeof defaultEmojiDataResolver

// module scope: frimousse keys its in-memory cache on the resolver's identity
export const resolveEmojiData: Resolver = async (locale, options) => {
  const local = await defaultEmojiDataResolver(locale, options)
  const en = locale === 'en' ? null : await Promise.resolve(defaultEmojiDataResolver('en', options)).catch(() => null)
  const byEmoji = new Map(en?.emojis.map((e) => [e.emoji, e]) ?? [])
  return {
    ...local,
    emojis: local.emojis.map((e) => {
      const other = byEmoji.get(e.emoji)
      const words = [...e.tags, ...[e.label, ...e.tags].map(fold), ...(other ? [other.label, ...other.tags] : [])]
      return { ...e, tags: [...new Set(words.map((w) => w.toLowerCase()))] }
    }),
  }
}
