---
name: video-motion-design
description: Make a motion design video with Remotion (React) on this server - an intro, a trailer, a product or feature video, a short / reel / story, animated text, a slideshow of screenshots, an explainer. Use when the user asks for a video, an animation, motion design, a short, a reel or a trailer.
---

# Motion design videos (Remotion)

Remotion is installed once on the server (`maxxing video status`). A video is a React project:
each frame is rendered from components, so everything is code - text, timing, transitions.

## 1. Create the project
```bash
maxxing video new <topic folder>/videos/<slug>      # e.g. projects/acme/topics/blog/videos/launch
```
It holds `src/Root.jsx` (one `<Composition>` per video: id, size, fps, duration), `src/Intro.jsx`
(an example scene), `public/` (images, audio, fonts: use them with `staticFile('logo.png')`).
`node_modules` is a link to the shared install: to add an npm package, first replace the link with a
real install (`rm node_modules && npm install --no-audit --no-fund <pkg>`), never install into the
shared one. If `maxxing video new` says Remotion is not prepared: `maxxing deps update` (as root).

## 2. Write it
- Agree on the format first: 1920x1080 (landscape), 1080x1920 (shorts, reels, stories), 1080x1080
  (square post); 30 fps; duration in frames (30 = 1 s).
- Build scenes with `<Sequence from={..} durationInFrames={..}>`; animate with
  `interpolate(frame, [a, b], [from, to], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'})` and
  `spring({frame, fps})`; fonts with `@remotion/google-fonts/<Font>`; images `<Img src={staticFile(..)}/>`;
  music or voice `<Audio src={staticFile('voice.mp3')}/>`.
- Readability first: big text (>= 60 px in 1080p), max ~8 words on screen, each text visible long
  enough to read (~0.3 s per word, 1.5 s minimum), safe margins (~5 %), strong contrast.
- Screenshots: show them whole and highlight with a frame or an arrow rather than zooming into
  unreadable crops.

## 3. Check, then render
```bash
cd <project> && npx remotion still src/index.jsx <Id> out/check.png --frame=<n>   # look at key frames
cd <project> && npx remotion render src/index.jsx <Id> out/<name>.mp4
```
Look at 2-3 stills (Read the PNG) before the full render and fix what is off. Rendering takes
roughly real time to a few times real time on a small server. Give the user the path of the MP4
(and a still as preview). Keep the project: changing a text later = edit + render again.

## 4. Assembling with ffmpeg (overlays, long edits)
A small server has a few GB of RAM and often no swap; a turn is capped at `unit_memory_max` (75 % of RAM by default),
and a command past it is killed (`Killed`, exit 137). ffmpeg decodes every `-i` input ahead of time and keeps
the frames it cannot use yet in memory, so:
- never give it dozens of inputs that start later in the video (one `-i` per PNG sequence / Remotion
  window, shifted with `setpts=...+T/TB`): 1080p RGBA frames are 8 MB each and fill the RAM in seconds.
  Put them in **one** input instead: an `ffconcat` list (one `file '.../element-%04d.png'` +
  `option framerate 30` + `duration` entry per sequence, a transparent PNG for the gaps - with
  `option framerate 30` on that one too: the list takes the clock of its first file, and a 25 fps
  first entry stretches every sequence x1.2), read by a
  `movie=filename=list.txt:f=concat:format_opts=safe\=0` source inside `-filter_complex` (a source
  filter is pulled frame by frame), then a single `overlay`. Same for a clip placed at the end:
  `movie=` / `amovie=` rather than `-i`.
- keep the video and the audio on the same clock: a video shifted with `setpts=PTS+T/TB` and an audio
  left at 0 make ffmpeg queue decoded frames until the OOM (shift both, or shift the video back at the end).
- before the full render, check the memory on a 30 s range (`systemd-run --scope -p MemoryMax=2G ffmpeg ...`
  or `/usr/bin/time -v`) and the timing of the whole list (`ffprobe -f concat -safe 0 -i list.txt
  -show_entries packet=pts_time`: steps of 1/30 s, never going backwards).
