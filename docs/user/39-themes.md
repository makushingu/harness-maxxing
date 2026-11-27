# Themes

**Settings -> Appearance -> Theme** sets the look of the whole interface, widgets and Agents views included. Two
themes are built in: **Solid** (the default: plain colors) and **Glass** (the bars, menus and dialogs see-through over
a soft backdrop). Installed themes sit next to them, each shown with a small preview.

Below the themes, **Options of <theme>** holds what you can still change: dark or light mode, accent color, background
and fonts. Picking a theme applies its suggested options once (a font, an accent...); you can change them afterwards.
When a theme fixes something itself (its own accent color, its own surfaces, a single mode), that option says so.

Everything is saved in this browser, like the rest of Appearance. Settings -> Extensions -> **Themes** lists the
installed themes with their state (in use, advanced CSS on or off, values ignored, folders that are not usable).

## Getting a theme

Themes are installed by Harness, never by a click: ask in any session ("make me a theme in the colors of my brand",
"install the theme `nord` from Community") or use **Ask Harness** under the themes. Harness uses the skill
`maxxing-theme`: it writes or reads the theme, checks it, installs it, and you pick it in Settings -> Appearance.

A theme is **data, never code**: a `theme.json` file of values (colors, sizes, shadows, fonts) and, optionally, images.
No script, no font or image loaded from the internet. That is why a theme cannot break the interface nor leak
anything, and why it keeps working after an update. The one exception is optional and kept apart: a single field of
**advanced CSS** (below), for what no value reaches.

## What a theme can never break

- **What it leaves out keeps the built-in value** (Solid or Glass, the theme's `base`). A theme can set three colors
  or all of them.
- **What it gets wrong is dropped**, with a warning: an unknown variable, a value of the wrong kind, a size out of
  range, anything that looks like a link or a script.
- **Unreadable text goes back to the built-in values**: text colors are checked against their surfaces (contrast
  4.5:1 for text, 3:1 for secondary text and buttons). A pair that fails returns to the built-in colors.
- **Updates add variables, never remove them**: an older theme simply gets the default of a new variable; a renamed
  one keeps working through an alias.
- A theme with only a dark (or light) part shows that mode only: the sun / moon button of the sidebar shows it, greyed
  out ("set by the theme"), and the command palette drops "Switch to light / dark theme". A theme removed while in use: the browser goes back
  to its base (Solid or Glass).
- If a theme ever bothers you: Settings -> Appearance -> **Solid**.

## Advanced CSS

For what no variable reaches (a border on one element, a letter spacing, a decoration), a theme may carry style
rules in **one field**, `"css"` of `theme.json`: a string, or a list of lines, at most 16 KB.

```json
"css": [
  "& aside { border-right: 2px solid var(--primary) }",
  "&.dark main h1 { letter-spacing: .02em }",
  "@media (max-width: 640px) { & main { font-size: 15px } }"
]
```

- The rules apply only while the theme is in use: they sit inside `html[data-theme-id="<id>"] { … }`, so every rule
  starts with `&` (the page), `&.dark` for the dark mode, `&:not(.dark)` for the light one.
- Refused as a whole, with a warning (the rest of the theme still works): `url()` and other images, `@import`,
  `@font-face` and every at-rule except `@media`, `@supports` and `@container`, `position: fixed`, `if()`, `attr()`,
  a `z-index` over 9, `<`, backslashes, control characters, unbalanced braces or quotes.
- **Unlike the values, these rules may look wrong after an update** (the interface they style changes). So an update
  that changes the interface's CSS **switches them off by itself**: Settings -> Appearance -> Options says "Switched
  off" with a button that asks Harness to check them. Harness looks at the pages with the new version, fixes the
  rules if needed and switches them back on (`maxxing themes verify <id>`). Rules edited by hand wait for the same
  check.
- You can switch them off yourself at any time: Settings -> Appearance -> Options -> **Advanced CSS** (this browser).
- On Community, a theme with advanced CSS is marked "may break after an update".

## The format

A theme is a folder `<workspace>/themes/<id>/`:

```
themes/nord/
  theme.json          the theme (required, at most 64 KB)
  wallpaper.webp      optional, a Glass theme's backdrop (png, jpg, webp or avif, at most 4 MB)
  wallpaper-dark.webp optional, the backdrop of the dark mode
  logo.png            optional, a logo shown instead of the Harness one (png, jpg, webp or avif, at most 512 KB)
  logo-dark.png       optional, the logo of the dark mode
  preview.png         optional, the picture of its Community listing (the card in Settings is drawn from its colors)
  README.md, LICENSE  optional
```

```json
{
  "schema": 1,
  "id": "nord",
  "name": { "en": "Nord", "fr": "Nord" },
  "description": "Arctic blues, calm and cold.",
  "author": "acme",
  "version": "1.0.0",
  "homepage": "https://github.com/acme/harness-theme-nord",
  "base": "solid",
  "light": { "background": "#f4f6f9", "foreground": "#2e3440", "primary": "#5e81ac", "radius": "0.4rem" },
  "dark":  { "background": "#2e3440", "card": "#3b4252", "foreground": "#eceff4", "primary": "#88c0d0" },
  "options": { "font": "plex", "mono": "jetbrains" },
  "wallpaper": "wallpaper.webp",
  "wallpaper_dark": "wallpaper-dark.webp",
  "logo": "logo.png",
  "preview": "preview.png",
  "css": ["& aside { border-right: 2px solid var(--primary) }"]
}
```

- `id`: 2-40 lowercase letters, digits and dashes, the name of the folder (not `solid` nor `glass`).
- `name`, `description`: a text, or one per language (`en`, `fr`...).
- `base`: `solid` or `glass`. A wallpaper only shows on a Glass theme.
- `logo`, `logo_dark`: your logo instead of the Harness one, in the sidebar, the phone header, the dialogs and the
  browser tab, while the theme is in use (one of the two is enough for both modes). Square, about 256 x 256, readable
  small. Not on the sign-in page (shown before you sign in) nor on the icon of an installed app (fixed at install).
- `css`: optional, see [Advanced CSS](#advanced-css).
- `light`, `dark`: the variables below (a missing block = that mode keeps the built-in look; only one block = the theme
  has that mode only).
- `options`: what the theme suggests when it is picked: `mode` (`dark`, `light`, `system`), `accent` (`blue`, `clay`,
  `violet`, `green`, `amber`, `rose`), `tint` (`neutral`, `tinted`), `density` (`comfortable`, `compact`), `font`
  (interface font: `inter`, `geist`, `plex`, `dmsans`, `manrope`, `jakarta`, `grotesk`, `outfit`, `sora`, `nunito`,
  `quicksand`, `comfortaa`, `rubik`, `sourceserif`, `lora`, `newsreader`, `fraunces`, `garamond`, `atkinson`,
  `lexend`, `jetbrainsui`, `martian`, `system`), `mono` (code font: `system`, `jetbrains`, `fira`, `geist`,
  `cascadia`, `sourcecode`, `victor`, `martian`, `roboto`, `redhat`, `atkinsonmono`).
- Colors: `#rgb`, `#rrggbb`, `#rrggbbaa`, `rgb()`, `hsl()`, `oklch()`, `oklab()`, `transparent`. Sizes: `px`, `rem`,
  `em`.

### The variables

| Variable | Kind | What it colors |
|---|---|---|
| `sidebar` | color | the frame: sidebar, gaps around the panel |
| `list` | color | the second bar (lists of sessions, agents...) |
| `background` | color | the content panel |
| `card` | color | cards, the message box |
| `popover` | color | menus, dialogs, the palette |
| `secondary` | color | secondary buttons |
| `sunken` | color | recessed zones |
| `foreground` | color | text |
| `card-foreground` | color | text on cards (default: `foreground`) |
| `popover-foreground` | color | text in menus and dialogs |
| `secondary-foreground` | color | text of secondary buttons |
| `muted-foreground` | color | secondary text (dates, hints) |
| `accent-foreground` | color | text of a hovered / selected row |
| `muted` | color | chips, soft hover |
| `accent` | color | hovered / selected row (not the accent color: that is `primary`) |
| `border` | color | lines |
| `input` | color | borders of fields |
| `sidebar-border` | color | lines of the bars |
| `ring` | color | focus ring |
| `overlay` | color | the veil behind a dialog |
| `primary` | color | the accent color: buttons, links, selection (set it and the accent option is the theme's) |
| `primary-foreground` | color | text on `primary` |
| `destructive` | color | delete buttons, errors |
| `destructive-foreground` | color | text on `destructive` |
| `success` | color | success |
| `warning` | color | warnings |
| `radius` | size (max 2.5rem) | corner rounding |
| `shadow-panel` | shadow | shadow of the content panel |
| `shadow-pop` | shadow | shadow of menus and dialogs |
| `glass-edge` | color | Glass: light on the top edge of surfaces |
| `glass-blur` | size (max 4rem) | Glass: blur behind bars and menus |
| `wall-a` | color | Glass: first color of the backdrop (top left) |
| `wall-b` | color | Glass: second color of the backdrop (bottom right) |
| `sf-h` | hue 0-360 | advanced: hue of every surface |
| `sf-c` | chroma 0-0.4 | advanced: how colored the surfaces are |
| `l-frame` | lightness 0-1 | advanced: lightness of the frame |
| `l-list` | lightness 0-1 | advanced: lightness of the second bar |
| `l-content` | lightness 0-1 | advanced: lightness of the panel |
| `l-card` | lightness 0-1 | advanced: lightness of cards |
| `l-float` | lightness 0-1 | advanced: lightness of menus |
| `l-accent` | lightness 0-1 | advanced: lightness of secondary buttons |
| `a-fill-1` | percent 0-40 | advanced: strength of the subtle fill |
| `a-fill-2` | percent 0-40 | advanced: strength of `muted` |
| `a-fill-3` | percent 0-40 | advanced: strength of `accent` |

The quickest way to a whole palette: set `sf-h` and `sf-c` (every surface takes that hue) or the five surfaces
`sidebar`, `list`, `background`, `card`, `popover`, then `foreground`, `muted-foreground`, `border` and `primary`.
A theme that sets a surface hides the Background option (the theme has its own).

## Commands

```
maxxing themes list                      installed themes (and folders that are not usable, with the reason)
maxxing themes check <folder>            read a theme like the interface will: what it sets, what is dropped and why
maxxing themes install <folder> [--force]   check it, then copy it into <workspace>/themes/<id>/
maxxing themes verify <id>               its advanced CSS was checked with this version: switch it back on
maxxing themes remove <id>
maxxing themes tokens                    the variables and their kind
```

A theme from outside (Community, GitHub): `maxxing community check <folder>` reads it first (remote `url()` or
`@import` in its CSS, files that are not theme data, its sha256), then
`maxxing themes install <folder> --sha256 <hash> --source <where it comes from>` installs only that content and records
it; a theme with findings asks to confirm. A reading aid, not a verdict: see
[13-page-extensions.md](13-page-extensions.md#what-a-package-does-before-it-is-installed).

`install` copies only `theme.json`, the images it names, `README.md` and `LICENSE`. An agent cannot install, verify or remove
a theme (it asks you in its answer).

## Sharing a theme on Community

A theme is listed on [Community](https://harness-maxxing.com/community) like an extension: put its folder in a public
GitHub repository (alone, or with `path` for one theme among several), add a `preview.png` (about 1200 x 630), and
submit it from the site or let Harness do it with your Community API key. Themes have their own category; a theme is
checked like the app does (the same rules) before it is accepted.
