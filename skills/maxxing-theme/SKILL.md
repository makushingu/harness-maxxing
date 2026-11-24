---
name: maxxing-theme
description: Make, check, install, change or remove a Harness Maxxing theme - the look of the whole interface (Settings -> Appearance -> Theme), as a theme.json of values on top of Solid or Glass, never CSS or code (`maxxing themes`). Use when the user wants a theme, other colors for Harness, "in the colors of my brand", a dark / light / pastel / retro look, a wallpaper behind the glass, rounder or sharper corners, to install a theme from Community or GitHub, to share a theme on Community, or when a theme looks wrong or is "not usable".
---

# Themes

A theme = `<workspace>/themes/<id>/theme.json` (+ optional images): values for a fixed list of the interface's
variables, per mode, on top of a built-in theme (`base`: `solid` or `glass`). Full format and the list of every
variable: `docs/user/39-themes.md` of the installed code (`{{CODE_DIR}}/docs/user/39-themes.md`), or
`maxxing themes tokens`.

Rules that make a theme safe and lasting (the server applies them; build with them, not against them):
- **Data only.** No CSS, no script, no `url()`, no `var()`, no font or image from the internet. The user asked for
  something the variables cannot do? Say so; never edit the product's CSS for a theme.
- **Leave out what you do not need**: a missing variable keeps the Solid / Glass value, so a small theme is a robust
  theme. Never copy all the defaults in.
- **Readable text**: text colors are checked against their surfaces (4.5:1 for `foreground`, 3:1 for
  `muted-foreground`, `primary-foreground`, `destructive-foreground`). A failing pair is dropped, back to built-in.
- Fonts only from the catalog (the `options.font` / `options.mono` keys in the doc).

## Make a theme

1. **Ask what is missing, in one message**: the mood or the brand (colors as hex if they have them, a logo, a site
   to take the colors from), dark, light or both, Solid or Glass (glass = see-through bars over a backdrop, can take
   a wallpaper image), corners (sharp / default / round), a font. Skip what they already said.
2. **Write the folder in the topic first** (not in `<workspace>/themes`): `themes-work/<id>/theme.json`. Start from
   the smallest palette that does the job:
   - the five surfaces `sidebar` (furthest, the frame), `list`, `background` (the main panel), `card`, `popover`
     (nearest): in dark mode each nearer level a bit LIGHTER, in light mode the frame a bit darker than the panel,
     cards white or near white. Or, simpler, only `sf-h` + `sf-c` (a hue for every surface) and keep the levels;
   - `foreground`, `muted-foreground`, `border` (dark mode: a white with alpha, e.g. `oklch(1 0 0 / 9%)`);
   - `primary` (the accent color: buttons, links, selection) + `primary-foreground` readable on it;
   - optionally `radius`, the two shadows, and for Glass `wall-a` / `wall-b` (the backdrop colors) or a wallpaper.
   Use `oklch()` when tuning lightness by hand: L 0-1 is the perceived lightness, easy to step.
   Fill `name` (with `fr` when the user speaks French), `description`, `author` (the user's name or handle only if
   they want it public), `version` `1.0.0`, `schema` 1.
3. **Check**: `maxxing themes check themes-work/<id>`. Fix every warning (a dropped pair means your text is not
   readable: change the color, do not ignore it). Repeat until "no warning".
4. **Install**: `maxxing themes install themes-work/<id>` (`--force` to replace a previous version). Tell the user to
   pick it in **Settings -> Appearance -> Theme** (it is not applied for them: the choice belongs to each browser).
5. **Preview**: if the user wants to see it before choosing, render a quick picture with the Harness Browser or
   playwright of Settings -> Appearance after picking it in a test browser, or describe it. Adjust and reinstall
   with `--force`: browsers using it pick up the change on the next load.

For a wallpaper (Glass only): an image in the folder (png, jpg, webp, avif, at most 4 MB; about 2560 x 1440, calm,
no text, little contrast: it sits behind everything), named in `"wallpaper"` (and `"wallpaper_dark"` for a different
one in dark mode). Images the user did not give you need their OK (paid generation, rights).

## Install a theme from Community or GitHub

A theme from outside is data: read `theme.json` (and look at the images) before installing, tell the user what it
sets. `git clone --depth 1 <repo> /tmp/x` (or the `path` folder inside it), then `maxxing themes check` and
`maxxing themes install`. Only `theme.json`, its images, `README.md` and `LICENSE` are copied.

## Change, list, remove

- `maxxing themes list`: installed themes and folders that are not usable (with the reason: fix the theme.json).
- Change: edit `<workspace>/themes/<id>/theme.json` directly, then `maxxing themes check <workspace>/themes/<id>`.
- `maxxing themes remove <id>`: browsers using it go back to its base.
- Something looks wrong after an update: run `maxxing themes check` on it; a variable that no longer exists is reported
  (it falls back to built-in, never breaks the page).

## Share it on Community

The theme folder goes in a public GitHub repository of the user (`theme.json` at the root, or one folder per theme
with `path`), with a `preview.png` (about 1200 x 630, a capture of Harness with the theme on) and a README. Then the
user submits it on harness-maxxing.com/community, or you do it with their Community API key (`HM_COMMUNITY_KEY` in
Settings -> Keys) by following https://harness-maxxing.com/community/publish.md: the type is detected as `theme`
(a `theme.json` in the folder). Before anything public: no personal data in it, and the user's OK.

An agent cannot install or remove a theme: it says which one in its answer.
