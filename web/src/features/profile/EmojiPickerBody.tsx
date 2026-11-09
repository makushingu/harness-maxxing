// The emoji grid of EmojiPicker (frimousse), loaded on first open. Its data (emojibase) is served by this server
// from /emojibase/<lang>/ (copied there by vite.config.ts), never fetched from a CDN.
import { EmojiPicker } from 'frimousse'
import { useLang, useT } from '@/i18n'
import { Spinner } from '@/components/ui'

export default function EmojiPickerBody({ onPick }: { onPick: (emoji: string) => void }) {
  const t = useT()
  const lang = useLang()
  return (
    <EmojiPicker.Root
      locale={lang === 'fr' ? 'fr' : 'en'}
      emojibaseUrl="/emojibase"
      columns={8}
      onEmojiSelect={({ emoji }) => onPick(emoji)}
      className="isolate flex h-[340px] w-[304px] max-w-full flex-col"
    >
      <EmojiPicker.Search
        autoFocus
        placeholder={t('emoji.search')}
        className="mx-2 mt-2 h-8 pointer-coarse:h-10 shrink-0 appearance-none rounded-md border bg-background px-2.5 text-sm outline-none placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring/50"
      />
      <EmojiPicker.Viewport className="relative mt-1 flex-1 outline-none">
        <EmojiPicker.Loading className="absolute inset-0 flex items-center justify-center text-muted-foreground">
          <Spinner />
        </EmojiPicker.Loading>
        <EmojiPicker.Empty className="absolute inset-0 flex items-center justify-center text-sm text-muted-foreground">
          {t('emoji.none')}
        </EmojiPicker.Empty>
        <EmojiPicker.List
          className="select-none pb-1.5"
          components={{
            CategoryHeader: ({ category, ...props }) => (
              <div className="bg-popover px-3 pt-2.5 pb-1 text-[11.5px] font-medium text-muted-foreground" {...props}>
                {category.label}
              </div>
            ),
            Row: ({ children, ...props }) => (
              <div className="scroll-my-1.5 px-1.5" {...props}>
                {children}
              </div>
            ),
            Emoji: ({ emoji, ...props }) => (
              <button
                type="button"
                className="flex size-9 items-center justify-center rounded-md text-xl leading-none data-[active]:bg-accent"
                {...props}
              >
                {emoji.emoji}
              </button>
            ),
          }}
        />
      </EmojiPicker.Viewport>
    </EmojiPicker.Root>
  )
}
