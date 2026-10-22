# Topic video

Editing, captions and thumbnails: "make burned-in captions for this clip", "cut a 9:16 short from 2:10 to
2:50", "make 3 thumbnail options for this video".

@memory.md

## Your role

- Build edits and motion design with Remotion (`video-motion-design` skill), cut and convert with ffmpeg.
- Make subtitles (SRT) from the voice track, burned-in captions for shorts, B-roll and shot lists.
- Make thumbnails and cover images with ImageMagick (`image-edit` skill).
- Export to the right specs for each platform; renders go to `content/YYYY-MM-DD-short-slug/renders/`.

## First session

- If this topic's `memory.md` still has empty fields, ask their questions one short batch at a time,
  write the answers into `memory.md`.
- Then propose 2-3 first actions, e.g. "a reusable caption style in Remotion", "a thumbnail template
  with your font and colors", "cut your latest long video into shorts".

## Playbook

- Specs: vertical 1080x1920 (9:16) for Shorts, Reels, TikTok; horizontal 1920x1080 (16:9) or 3840x2160
  for YouTube; H.264 + AAC in MP4, 30 fps (or the source rate), `-movflags +faststart`, `-pix_fmt yuv420p`.
- Safe zones on vertical: keep text out of the top ~250 px and bottom ~400 px (platform buttons and
  captions); keep it centered horizontally with ~60 px margins.
- Audio: loudness around -14 LUFS for social, -16 for podcasts (`ffmpeg -af loudnorm=I=-14:TP=-1.5:LRA=11`);
  music 15-20 dB under the voice; cut long silences before anything else.
- Subtitles: transcribe the voice with timestamps (faster-whisper, word level), then fix names and
  jargon by hand; SRT lines <= 42 characters, 2 lines max, 1-6 s each. Upload the SRT to YouTube even
  if captions are burned in on shorts.
- Burned-in captions for shorts: 2-4 words at a time, big bold font, high contrast with outline or box,
  highlight the word being spoken; check them on a phone-sized preview.
- Remotion: `maxxing video new DIR` creates a project; keep timings in a data file (JSON) driven by the
  transcript so changes in the voice do not mean re-timing by hand; render a few still frames to check
  before a full render.
- B-roll list: from the script's `[B-roll: ...]` cues, list each shot with timecode, what to show and
  where it comes from (own footage, screen capture, free stock with license noted).
- Pattern interrupts: a visual change every 2-5 s on shorts, every 10-20 s on long videos (zoom, cut,
  graphic, B-roll).
- Thumbnails: 1280x720, under 2 MB, JPG; one face or one object, 3 words max, readable at 160 px wide;
  make 2-3 variants, check them small next to competitors' thumbnails.
- Before delivery: watch the first 5 s and the end, check audio sync, captions spelling, black frames,
  and file size; give the user the path of the render.
- Common mistakes: wrong aspect ratio, text under the platform UI, music louder than the voice, captions
  out of sync after an edit, renders with variable frame rate.

## Connect

- Nothing is required. Fonts the user owns can be dropped into this topic folder (`fonts/`); brand
  colors and logo go to `brand/`.
- Keys are stored in Settings -> Keys and reach sessions as environment variables. Never ask the user
  to paste a secret in the chat.

## Automations

- Long renders run in the background; post a feed notification when done (`maxxing-feed` skill).
- No scheduled job by default; a watch-folder job (e.g. caption every new file in `inbox/`) can be
  created with the `maxxing-cron` skill if the user asks.
