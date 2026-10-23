# UI design & frontend rules (v2)

How the web app is built and how to add to it without breaking the look or the feel. Read this before writing a
page. Code lives in `web/` (React 19 + TypeScript strict + Vite + Tailwind v4 + Radix + TanStack Query + Zustand).

```
web/
  index.html               theme bootstrap script (no flash) — mirrors src/stores/ui.ts
  vite.config.ts           dev proxy /api + /ext → MAXXING_API (default http://127.0.0.1:8801)
  mock/server.mjs          zero-dependency mock of the whole API (port 8809, scenarios) — see "Mock"
  src/
    main.tsx  App.tsx      providers (QueryClient, Tooltip, Router, ConfirmHost, Toaster)
    routes.tsx             THE route table (lazy pages)
    pages/Root.tsx         boot gate (setup / login / onboarding redirects)
    pages/<page>/index.tsx one folder per page (default export = page component)
    features/<domain>/     building blocks shared by onboarding and settings (Claude, Telegram, backup…)
    components/ui/         the design system (import from '@/components/ui')
    components/shell/      app shell: Sidebar, TouchNav (touch layout), Page/PageHeader, CommandPalette, Health…
    commands/              palette registry + keyboard shortcuts
    lib/api.ts types.ts    HTTP client + every API.md payload type
    lib/queries/*.ts       React Query hooks per domain, query keys in keys.ts
    lib/sse.ts             useEventSource() + global bus (/api/stream)
    stores/ui.ts           persisted UI prefs (theme, accent, tint, density, fonts, language, sidebar, presentation, tourDone)
    pwa/                   service worker registration, update toast, install prompt / iOS dialog
    tour/                  guided tour (steps.ts = the script, Tour.tsx = overlay + card)
  sw/sw.js                 service worker source (emitted as dist/sw.js by the `maxxing-sw` plugin)
  public/                  manifest.webmanifest, offline.html, icons/ (PNG, from scripts/gen-icons.py)
    i18n/{en,fr}.ts        dictionaries; useT()
    styles/globals.css     tokens (CSS variables) + markdown + highlight theme
```

Commands: `npm ci`, `npm run dev` (Vite on :5173, `MAXXING_API=http://127.0.0.1:8809 npm run dev` for the mock),
`npm run build` (`tsc -b` + `vite build` → `web/dist`, committed), `npm run mock` (serves `dist` + fake API on :8809).

## 1. Tokens

All colours are CSS variables in `styles/globals.css`, exposed to Tailwind through `@theme inline`
(`bg-background`, `text-muted-foreground`, `border-border`, `bg-primary`…). **Never hard-code a colour** — the only
exceptions are chart series (`--series-1..6`) and brand-neutral swatches in the accent picker.

| Token | Use |
|---|---|
| `background` / `foreground` | page |
| `card`, `popover` (+ `-foreground`) | raised surfaces (cards / menus, dialogs) |
| `muted` / `muted-foreground` | subtle fills, secondary text |
| `accent` / `accent-foreground` | hover & selected rows (neutral, NOT the brand colour) |
| `primary` / `primary-foreground` | the user's accent colour: primary buttons, links, active nav, focus ring |
| `secondary` | secondary buttons, segmented/tab active background |
| `destructive`, `success`, `warning` | status (use at /10–/15 opacity for fills, solid for dots & text) |
| `border`, `input`, `ring` | hairlines, input borders, focus |
| `sidebar`, `sidebar-border`, `overlay` | shell & modal backdrop |

- **Neutrals = zinc.** Dark is the default (`.dark` on `<html>`), light and system are available.
- **Accent**: one of `blue` (default) · `clay` (shown as Orange) · `violet` (Purple) · `green` · `amber` (Yellow) · `rose` (Red), each on the hue of its colored logo (`data-accent` on `<html>`, a light and a dark step each; stored per browser, an unknown value falls back to `blue`). The logo follows it: `public/icons/logo-<accent>-{64,128}.png` (sidebar, sign-in, splash, browser tab; `logoSrc()` in `lib/accent.ts`).
- **Background**: `data-tint` on `<html>` = `neutral` (default, zinc greys) or `tinted` (surfaces, borders and muted text take a low-chroma shade of `--accent-h`, the hue set by each `[data-accent]` rule; light and dark overrides in `globals.css`).
- **Fonts**: 23 interface fonts in groups (`FONT_GROUPS`: modern, character, rounded, serif, readable, mono, system; default `inter`) and 11 code fonts (default `system`) (`lib/fonts.ts`, mirrored in the `index.html` inline script, all bundled with `@fontsource-variable`; only Inter is in the entry CSS, the others are loaded on demand by `loadFont`, applied as `--mx-font-sans` / `--mx-font-mono` on `<html>`).
- **Radius**: `--radius` 10 px → `rounded-sm/md/lg/xl`. Cards `rounded-xl`, controls `rounded-md`.
- **Spacing**: Tailwind's 4-px scale only (`gap-2` = 8 px…). Card padding = `var(--pad-card)` (20 px comfortable,
  14 px compact — `data-density`).
- **Type**: Inter Variable (self-hosted, `@fontsource-variable/inter`), body 14 px / 1.5. Scale: page title 15–16 px
  semibold (header), section title 20 px, card title 14–15 px medium, body 14, secondary 13, meta 11–12.
  Numbers in columns use `tabular-nums`; big standalone figures do not.
- **Focus**: every interactive element shows a 2 px `ring` on `:focus-visible`. Never remove it.
- **Motion**: 100–220 ms (`animate-in`, `animate-sheet-up`…). `prefers-reduced-motion` disables all animation
  globally — do not add JS animations that ignore it.
- **Icons**: `lucide-react`, 16 px in controls (`size-4`), 18–20 px in navigation. No emoji in the UI.
  Widgets/extensions name icons in kebab-case; `<NamedIcon name>` renders the curated set in
  `components/ui/icon.tsx` (unknown → puzzle). Add names there when needed (keeps the bundle small).

## 2. Components (`@/components/ui`)

| Component | Notes |
|---|---|
| `Button` | variants `default · secondary · outline · ghost · destructive · link`, sizes `default · sm · lg · icon · icon-sm`. `loading` shows a spinner **without changing the width**. 44 px tall on mobile automatically. |
| `Input`, `Textarea` (autosize `minRows/maxRows`), `SecretInput` (show/hide), `Label` | inputs are 16 px on touch screens (no iOS zoom), 14 px with a fine pointer. |
| `FormField` | label + one control + hint/error; wires `id`, `aria-describedby`, `aria-invalid`. |
| `Select` (shorthand `options`), `Combobox` (`@/components/ui/combobox`, not in the barrel: searchable, long lists; `options` may be a function built on open), `Segmented` (2–5 exclusive options), `Switch`, `Checkbox` | |
| `Card*`, `Badge` (`default · secondary · outline · success · warning · destructive · muted`), `Separator`, `Kbd` + `MOD` | |
| `Dialog*` | centered on desktop, **bottom sheet on mobile** (swipe down to close, `ui/sheet-drag.ts`). |
| `AlertDialog*` + `confirm({title, description, destructive, confirmText, typeToConfirm})` | `await confirm(...)` → boolean. `typeToConfirm` for irreversible actions (restore…). |
| `Sheet*` | side drawer (right/left) on desktop, bottom sheet on mobile; `side="bottom"` everywhere. Bottom sheets close with a swipe down (handle, header, or content scrolled to the top; `data-no-drag` opts an element out). |
| `DropdownMenu*` (`destructive` items), `Popover*`, `Tooltip` (shorthand `content`), `Tabs*`, `ScrollArea` | Radix-based, keyboard accessible. |
| `Skeleton`, `SkeletonText`, `Spinner`, `EmptyState`, `ProgressBar`, `StatusDot` | see §4. |
| `toast.success/error/info` + `<Toaster/>` (sonner) | bottom-right desktop, top-center mobile. |
| `CodeBlock` (block or `inline` one-liner with copy), `CopyButton` | |
| `Markdown` (`@/components/ui/markdown`, lazy-load it) | GFM, highlight.js, raw HTML escaped, unsafe URLs dropped, `/routes` via the router, external links `noopener noreferrer nofollow` in a new tab, code blocks with copy. `onLink(href)` to rewrite links (docs). |
| `QRCode` (`@/components/ui/qr-code`, not in the barrel) | client-side SVG (uqr). |
| `Avatar`, `NamedIcon`, `initials()` | |
| `Sensitive`, `useMask()`, `usePresentation()` | presentation mode, see §6. |

Shared feature blocks (`src/features`): `Callout` (inline result/explanation, tones success/error/warning/info),
`Steps` (numbered instructions), `OptionCard` (radio card), `SettingRow` (label left, control right), and the
domain components reused by onboarding **and** settings: `ClaudeConnect`, `ClaudeDefaults`, `CreateProjectTopic`
(+ `SlugPreview`), `TelegramSetup` (+ `ThreadList`), `BackupSetup` (+ `BackupWhy`), `RegionFields`.

## 3. Layout rules

- **Two layouts**, decided once by `html[data-compact]` (`stores/media.ts` `isCompact()` / `useCompact()`, copied in
  `index.html` before the first paint): **desktop** (sidebar 232 px, collapsible to 60 px icons — auto-collapsed in
  a 768–1023 px window) and **touch** (phones, tablets = `(pointer: coarse) and (hover: none)`, any window < 768 px;
  Settings → General → Layout forces it per device). The Tailwind variants `md:` / `max-md:` are redefined in
  `globals.css` on that attribute (not on the width): `md:` = desktop layout, `max-md:` = touch layout. `sm:`,
  `lg:`, `xl:` stay width breakpoints.
- **Touch layout** (`components/shell/TouchNav.tsx`): no sidebar, no tab bar. Every top bar has ☰ on the left
  (`TouchSessionsButton`: sessions drawer = `SessionTree touch`, `pages/sessions/SessionsPanel.tsx`) and ⊞ on the
  right (`TouchAppButton`: app drawer = every entry of the sidebar). Drawers = `components/ui/drawer.tsx` (side
  panels on phones too, swipe back to close); any navigation closes them; edge swipes open them in the installed app.
  `/sessions` always shows one session full screen (the last one). Row menus open with a long press
  (`lib/long-press.ts`). A new sidebar entry must also appear in the app drawer.
- `<main id="main">` is the only scroll container
  (`scrollbar-gutter: stable` → no horizontal jump when content grows).
- **Every page** renders `<Page title description actions width>` (sticky header + centered body,
  `width` = `narrow 768 · default 1152 · wide 1600 · full`). Full-bleed pages (Sessions, Files) render
  `<PageHeader>` + their own body. The header **is** the top bar in the touch layout
  too (☰ on the left, ⊞ on the right): never add a second top bar.
- Page actions: ≤ 3 visible buttons; on mobile use icons (`<span className="max-sm:hidden">label</span>`) or a "…"
  `DropdownMenu`.
- Settings-like pages: stacked `SettingsCard`s (`grid gap-6`), danger zone last (`danger` prop).
- **Density**: rows 40 px comfortable / 32 px compact (`--row-h`); lists use `divide-y` inside a bordered card.
- Responsive targets: 375 / 768 / 1280 / 1920 px. Test at least 375 and 1280.

### Mobile
- Inputs 16 px (automatic), touch targets ≥ 44 px (buttons do it automatically below `md`), `Dialog`/`Sheet`
  become bottom sheets, respect `--safe-top/bottom/left/right`.
- iOS zooms into any field under 16 px when it gets the focus. `globals.css` forces 16 px with `!important` on
  touch screens (`pointer: coarse`) for inputs, textareas, selects and `contenteditable` (the code editor), so a
  `text-xs` / `text-[13px]` on a field is harmless there - never rely on a smaller size on mobile.
- No page zoom on touch screens (owner's decision, 2.0.0a77): `html { touch-action: pan-x pan-y }` (no double-tap,
  no pinch), viewport `maximum-scale=1, user-scalable=no`, and `lib/mobile-viewport.ts` cancels iOS Safari's pinch
  (`gesturestart` / two-finger `touchmove`), which ignores the viewport in a tab. The viewport has `interactive-widget=resizes-content` (Android: the keyboard resizes the page).
- Keyboard (`lib/mobile-viewport.ts`, touch screens): `html[data-kbd]` while a field has the focus sets
  `--safe-bottom` and `--safe-bottom-ui` to 0; `--kbd-inset` (bottom of the
  layout covered by the iOS keyboard) and `--vvh` (visual viewport height) keep bottom sheets above the keys. Fixed
  bottom elements use `bottom-[var(--kbd-inset)]` when they hold a field. The document never scrolls: iOS leaves it
  scrolled after the keyboard or a return from the background, so it is put back at 0.
- Closing animations: `data-[state=closed]:animate-sheet-down` / `animate-overlay-out` / `animate-out` (Radix keeps
  the element until the animation ends).
- Full-screen layers of the installed app (session on a phone) go back with a swipe from the left edge
  (`lib/edge-swipe.ts`; only in standalone mode, a browser tab keeps its own gesture).
- A control smaller than 28 px (icon "×", column selector, switch, checkbox) gets an invisible hit area:
  `relative before:absolute before:-inset-2.5 before:content-['']` (as `Switch` / `Checkbox` do).
- Horizontal overflow is a bug: give flex children `min-w-0` and long strings `truncate` / `break-all`.

## 4. States

| Situation | Do |
|---|---|
| First load of a page / card | **Skeleton with the final footprint** (same height as the content). Never a centered spinner, never an empty flash. |
| Refreshing data already shown | keep the old data visible (React Query does it), optional small spinner in the trigger, `opacity-60` on the card. |
| Lazy route chunk loading | nothing to do: the router keeps the previous page and shows the 2 px top progress bar after 120 ms. |
| Empty list | `EmptyState` with an icon, one sentence and a call to action. |
| Load error | inline `EmptyState tone="error"` / `Callout tone="error"` with a Retry button where it happened. |
| Result of an action (saved, sent, deleted) | `toast.success` / `toast.error` (default via `useMut`). |
| Form validation / a server refusal tied to a field | **inline** under the field (`FormField error`), `errorToast: false` in `useMut`. |
| Destructive action | `await confirm({destructive: true})`; irreversible → `typeToConfirm`. |
| Long operation (update, test call) | progress inline in the card, `aria-live="polite"`. |

## 5. Data, live updates, navigation

- **API client** `lib/api.ts`: `api.get/post/put/patch/del/upload`, same-origin cookie, `X-Maxxing: 1` on every
  non-GET, throws `ApiError {status, code, message}`. A 401 anywhere → redirect to `/login?next=<here>` (pass
  `noAuthRedirect: true` for calls where 401 is a form error, e.g. password change). `errorMessage(e)` for display.
- **Types**: `lib/types.ts` mirrors API.md exactly. Change API.md first, then types, then code.
- **Queries**: one hook per endpoint in `lib/queries/<domain>.ts`; keys in `keys.ts` always start with the domain
  (`['sessions', …]`). Mutations use `useMut(fn, {invalidate, successToast, errorToast, optimistic})`. Every toggle,
  switch or small edit is **instant**: `optimistic: (vars) => [{ key, update }]` patches the cache before the request
  and is rolled back on error (see `usePatchSession`); never make a button wait for a refetch.
- **Live**: the shell connects `/api/stream` once; `BUS_KEYS` maps each bus topic to the query prefixes it
  invalidates. Never poll what the bus already pushes (health also refetches every 60 s as a safety net).
  For per-resource streams use `useEventSource(url | () => url, {eventName: handler}, {onReconnect})` — pass a
  function to resume from the latest offset after a reconnect.
- **URLs are the state** for anything shareable: `/sessions?path=<topic>&session=<id>&new=1`,
  `/files?path=<abs path>`, `/tasks?task=<id>`, `/crons?job=<id>`, `/settings/<section>`, `/docs/<slug>`,
  `/x/<extension id>`. Built-in dashboard links use these routes.

### Adding a page
1. `src/pages/<name>/index.tsx` with `export default function NamePage()` rendering `<Page …>`.
2. Add a lazy entry in `src/routes.tsx` (`{ path: '<name>/*', lazy: page(() => import('./pages/<name>')) }`).
   The page owns its sub-paths (nested `<Routes>` inside, or `children` in the table).
3. Primary navigation item? Add it to `components/shell/nav.ts` (sidebar, touch app drawer, palette and `g <key>` follow).
4. Palette commands: `useRegisterCommands('<page>', [{id, title, group, icon, perform}], deps)` while mounted;
   search-as-you-type sources: `useRegisterProvider({id, group, search(q, signal)})`.
5. Shortcuts: `useHotkey('mod+enter', fn)` (single keys are ignored while typing); document them in the
   shortcuts dialog (`GLOBAL_SHORTCUTS` or a page section).
6. Strings in `i18n/en.ts` **and** `i18n/fr.ts`, user data wrapped in `<Sensitive>`.

### Extension pages
`/x/:id` imports `/ext/<id>/page.js` and calls `mount(el, ctx)`; `ctx = {id, api(path, {method, body, query}),
navigate(route), theme: 'dark'|'light', t(key)}`. `ctx.api('notes')` → `/api/ext/<id>/notes` (JSON, CSRF header),
resolves to the parsed JSON, rejects with an `Error`. The returned function is called on leave.

**UI kit for extensions** (`server/maxxing/assets/ui-kit.css`, served at `/ext/ui-kit.css`): the look of this design
system as plain `ui-*` classes, so pages and HTML widgets written by Claude (no React, no Tailwind) look like the app:
`ui-page ui-section ui-grid ui-row ui-stack`, `ui-h1/h2/h3 ui-text ui-muted ui-small ui-label`, `ui-card` (+ `-header`,
`-footer`), `ui-tile` (clickable card: `ui-icon-box` + `<div><b/><span/></div>`), `ui-btn` (+ `ui-secondary ui-outline
ui-ghost ui-danger ui-sm ui-icon-only`), `ui-field ui-input ui-select ui-textarea ui-check`, `ui-badge` / `ui-dot`
(+ `ui-success ui-warning ui-error ui-primary`), `ui-list ui-table ui-table-wrap ui-stat ui-progress ui-steps ui-callout ui-empty
ui-skeleton ui-code ui-kbd ui-link`. Scoped to `.mx-ext` (the page host) and `[data-mx-kit]` (`<html>` of a widget frame),
inside `:where()` so an extension's own CSS always wins; every colour is a theme variable (the widget frame receives
them all by message). `ctx.icon(name)` gives pages the curated icons of `NamedIcon`; Card list items take `icon` too.
When a component of `components/ui` changes its look, change its `ui-*` twin. No emoji in built-in cards, packs or
the default extensions: icons.

## 6. Presentation mode (mandatory)

A persisted flag (`useUI().presentation`, toggle in the sidebar / touch app drawer / palette / `Shift+P`).
`<Sensitive>{value}</Sensitive>` renders the value normally, or a mask (`••••`) when active — **the real value is
not rendered at all**, so nothing leaks in the DOM, tooltips or screenshots. `block` for paragraphs,
`placeholder` for custom masks (charts, QR codes), `useMask()` for strings in attributes/inputs.

**Rule: every page wraps user data** — names of projects/topics/sessions/files, paths, message text, numbers that
describe the user's business, tokens, ids, usernames, repository names, log lines. What *names an action or a
section* (labels, buttons, headings of the UI) stays readable. Settings › General has "Presentation mode by
default" (applied once per new browser).

## 7. i18n

`useT()` → `t('key', {vars})`. English is the reference (`en.ts`); `fr.ts` is typed
`Record<keyof typeof en, string>` so a missing translation fails the build. Plurals: add `key#one` (used when
`count` is 1 — French: 0 or 1). Keys are grouped by area (`common.*`, `nav.*`, `settings.*`, `onb.*`…). The language
comes from server settings once signed in (stored locally too for the login page). Format dates/numbers with
`lib/format.ts` + the current language and the configured time zone.

Loading: each dictionary is split at build time (`i18nSplit` in `vite.config.ts`) by namespace (the key's first
segment). `i18n/groups.ts` lists the namespaces that leave the core, by group (`settings`, `auth`, `infra`, `git`,
`tasks`, `files`, `show`); the core (everything else) is awaited before the first render. A route declares the
groups it shows (`page(() => import('./pages/tasks'), ['tasks'])` in `routes.tsx`, preloaded by `index.html` too) and
a lazy component wraps its import with `withGroups(['infra'], () => import(…))`. A key from a group that is not
loaded yet renders as an empty string and triggers its loading (then `useT` re-renders): a new namespace shown by the
shell or the dashboard stays out of `groups.ts`.

## 8. Do / Don't

Do
- Use the components above; extend them rather than restyling ad hoc.
- Reserve space for anything that loads (skeletons, fixed-height charts, error lines under fields).
- Keep the previous data on screen while refetching; patch caches from mutation responses when possible.
- Make every action reachable by keyboard; dialogs trap focus and restore it (Radix does it).
- Give icon-only buttons an `aria-label` (and a `Tooltip` on desktop).

Don't
- `window.alert/confirm/prompt` — use `toast`, `confirm()`, a `Dialog`.
- Spinners for page loads, layout shifts when data arrives, content that jumps when a scrollbar appears.
- Hard-coded colours, raw `fetch` in components, `any` in API types, strings outside the dictionaries.
- Render user data outside `<Sensitive>`.
- Name endpoints or files `/log`, `/track`, `/ads`, `/stats` (ad blockers).
- Load a CDN: everything is bundled (fonts included) — the UI must work offline behind a VPN.

## 9. Mock & visual checks

`web/mock/server.mjs` implements every API.md endpoint with in-memory, product-neutral data and serves `web/dist`:
`MOCK_PORT=8809 MOCK_SCENARIO=ready|onboarding|login|setup|maxxing node mock/server.mjs`
(`maxxing`: 30 more sessions that keep finishing at random, for Maxxing mode; `MOCK_PASSWORD=…` asks for that password;
`MOCK_DIST=…` serves another build)
(`POST /__mock/scenario {"name"}` resets at runtime; setup token `dev-token`, password `password123`).
Visual pass = Playwright screenshots at 375 / 768 / 1280 / 1920 of every page in dark and light, plus a check that
the console has no errors.

## 10. PWA & guided tour

**PWA.** `public/manifest.webmanifest` + icons (`scripts/gen-icons.py` renders them from the logo; PNGs are
committed). `sw/sw.js` is hand-written; the `maxxing-sw` Vite plugin injects the build version (hash of the output
file names → cache names `mx-shell-<v>` / `mx-assets-<v>`) and the app-shell precache list. Strategies: navigations
network-first → `offline.html` when the server is unreachable (HTML is never cached); `/assets/*` cache-first;
other static files stale-while-revalidate; **`/api/*`, `/ext/*`, non-GET and cross-origin requests are never
intercepted**. Old caches are deleted on activate. A new build ⇒ new `sw.js` ⇒ toast "New version available —
Reload" (`SKIP_WAITING`, then reload on `controllerchange`). The server sends `sw.js`, `manifest.webmanifest` and
`offline.html` with `Cache-Control: no-cache`. The SW only registers in production builds on secure origins
(HTTPS or localhost). "Install app" (user menu, touch app drawer, palette, Settings › General) uses the deferred
`beforeinstallprompt`, or explains Share → Add to Home Screen on iOS; hidden once installed (standalone).

**Guided tour.** Steps target `data-tour="<id>"` attributes (`nav`, `tree`, `new-session`, `composer`, `palette`,
`nav-<page>`, `health`, `menu`); the first *visible* element of each id is used, several ids are unioned. A step
can route first (e.g. open a new-session column to show the composer); a target that does not show up within 3 s
is skipped — the tour never blocks. Keep these attributes when refactoring the shell. It starts once after
onboarding (`mx-tour-pending` in sessionStorage, `tourDone` in the UI store) and is replayable from the Help
group of the user menu, the palette and Settings › General. The closing card links to the
`projects/tutorial/topics/1-first-steps` topic when it exists (else to the docs).
- Counters: `CountBadge` / `CountDot` (`@/components/ui`) - round, sky for unread, accent for running; they
  pulse (`.mx-badge-pulse`) only when the user turned on Settings -> Notifications -> "Pulsing badge".

## 11. Motion & performance

- Motion is light and short (140-340 ms), **transform and opacity only**, and always disabled by
  `prefers-reduced-motion` (global rule in `globals.css`). Fill mode is `backwards`, never `both` or
  `forwards`: a finished animation must not keep a GPU layer alive per row.
- Utilities (`globals.css`): `.mx-rise` (item entrance), `.mx-card-in` (dashboard widgets, 32 ms apart, `--i` capped at 6), `.mx-unfold` (group opening), `.mx-fade`; stagger
  siblings with `style={{ '--i': n }}` (cap `n` at 10). `#main > *` fades each routed page in - **opacity
  only**, a transform would make the page the containing block of its `fixed` overlays.
- Dashboard cards build their content after `.mx-card-in`: `.mx-grow-y` (chart bars), `.mx-draw` (chart line,
  `pathLength="1"`), `.mx-sweep` (timeline tracks, `grow` progress bars), `.mx-dot-in` (timeline events, lane then
  time order via `--i` / `--x`), `.mx-rise` on list / table rows, a count-up on numeric stats (`useCountUp`, rAF,
  text only). A card below the fold carries `.mx-wait` (`animation-play-state: paused` on it and its children) and
  the `InView` context is false until it scrolls into view (IntersectionObserver), so its entrance is seen; never
  under reduced motion. When the grid changes (feed panel, widget shown / hidden / moved) `useGridFlip` slides the
  cards (2-D FLIP, transform only, 340 ms). The whole build of a card stays under ~0.9 s.
- A page is fully on screen within ~0.5 s of its data: a stagger never delays the last item by more than
  ~200 ms (cap `--i`), and an entrance does not replay when the user comes back to a page.
- First load: `index.html` sets `html[data-boot]` and paints a splash inside `#root`; `AppShell` removes
  the attribute after 1.3 s. Boot-only animations are scoped to it (`.mx-boot-side`, `.mx-boot-item`).
- Never use `backdrop-filter` / `backdrop-blur` anywhere: it is expensive on Windows and integrated GPUs and
  makes text look soft. Use an opaque or near-opaque background.
- Entrance animations run once: the session tree animates only nodes mounted during its first reveal
  (`TreeIntro`), on the first visit of the tab only; folders opened later only unfold. Switching the list Projects / Sessions replays that intro
  for the new view. Never stack two entrance animations on one element.
- Counters (`CountBadge`) pop in and shrink out with the Web Animations API (no clash with the CSS pulse): keep
  them mounted (`count={0}`) and give their wrapper `empty:hidden` instead of `{n > 0 && …}`, or they vanish.
- `useGlobalBus` batches server invalidations (250 ms) and `AppShell` prefetches the page chunks and the
  sessions list when idle (skipped on Save-Data / 2G).
- Settings: `SectionStack` wraps each card in `.mx-rise` (28 ms apart, cards after the 5th together, section heading first); the desktop sub-nav
  highlight is one absolute element moved with `transform` (items are `h-9` + `gap-0.5` = 2.375rem apart).
- Lists that change under the user (session rows, columns): `lib/presence.ts`. `usePresence` keeps a removed
  item rendered while it leaves; `animateOut` takes it out of the flow (absolute, parent `relative`) and fades
  it; `useFlip` slides the others from their previous place; `animateIn` fades + slides new ones. Transform and
  opacity only - never animate width/height (a column re-lays its whole thread out every frame). Off while the
  tree is filtered (`ms = 0`) and under `prefers-reduced-motion`.
- Long homogeneous lists: `.mx-cv` (`content-visibility: auto`) on rows of fixed height.
- Code that is not needed for the first paint (palette, tour, install dialog, shortcuts) is a lazy chunk
  mounted through `WhenIdle` in `AppShell`; keep their stores in separate files so the chunk can split.
- Files are opened with `openFileViewer(path, list)` (`features/files/viewerStore.ts`) - never a page-local
  drawer: one viewer (panel / fullscreen, ← / →, folders) for the whole app, its chunk loads on first open. A
  clickable path in a thread carries `data-mx-file` (or is a `#mx-file=` link) so ← / → can find it. Renderers
  per kind live in `features/files/viewers.tsx` (media, pdf, markdown) and `rich.tsx` (CSV, HTML, archive,
  font, folder); `PreviewBody` picks one.
- `window.__mxAuth` (set in `index.html`) is the auth-state request started before the bundle loads;
  `fetchAuthState` consumes it once.
- Boot: `index.html` preloads the page chunk of the opened URL and the UI language's dictionary chunks (core + the
  route's groups, see §7; route table read
  from `src/routes.tsx` at build time); `lib/boot.ts` starts the first screen's API calls with the hooks' own
  query keys as soon as the early auth check says signed in. Keep new pages in `routes.tsx` so they get it.
- Page data: `pages/pageData.ts` maps a URL to its page's main queries (`prefetchPageData`). It is called by the
  boot prefetch, by the AppShell route `loader` (in parallel with the lazy chunk, again on a page change) and by
  the sidebar / tab bar links on hover, focus or touch (`usePrefetchLink`, chunk + data). A new page adds its
  queries there, built with the same `xxxQuery()` factories as its hooks (same keys, so the hook finds them).
- Refetch on focus is off for `LIVE_KEYS` (`lib/queries/keys.ts`: data the bus keeps fresh); `useGlobalBus`
  refreshes them once when a tab comes back after 60 s hidden. Add a key there only if every change to it is
  pushed by the bus.
- Long lists: render progressively (first slice, then more as the end comes near, see `files/Listing.tsx`) or
  page them; a list that can reach thousands of rows never mounts them all at once.
- Build output: `maxxing-precompress` (vite.config.ts) writes `<asset>.br` (Brotli 11) next to each JS/CSS file
  and preloads the Latin Inter font; the server (`app.py`, `_mount_spa`) sends the `.br` twin with
  `Content-Encoding: br` when the browser accepts it.
- Accent in images: `src/lib/accent.ts` (sRGB copy of the accent palette, mirrored in `index.html` and
  `offline.html`) drives every logo: favicon, splash, installed-app manifest and icons, iOS home-screen icon,
  notifications. A new accent or a new logo: change the drawing in `web/scripts/gen-icons.py` and rerun it; never hard-code a
  blue icon, and use the SVG (`logoSrc`) wherever a browser draws it.
