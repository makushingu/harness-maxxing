---
name: image-edit
description: Resize, crop, convert (webp, png, jpg), compress, add a border or text, make thumbnails or a contact sheet, strip metadata - single images or whole folders - with ImageMagick and ffmpeg. Use when the user asks to edit, convert, shrink or batch-process images.
---

# Image editing (ImageMagick / ffmpeg)

Work on copies (write to a new name or an `out/` folder) unless the user asks to replace files.

| Task | Command |
|---|---|
| Resize (max 1600 px wide, keep ratio) | `convert in.jpg -resize '1600x>' out.jpg` |
| Convert + compress for the web | `convert in.png -quality 82 out.webp` |
| Crop to a ratio (centered 16:9) | `convert in.jpg -gravity center -crop 16:9 +repage out.jpg` |
| Square thumbnail 400 px | `convert in.jpg -resize 400x400^ -gravity center -extent 400x400 thumb.jpg` |
| Strip metadata (GPS, camera) | `convert in.jpg -strip out.jpg` |
| Text on an image | `convert in.jpg -gravity south -pointsize 48 -fill white -annotate +0+40 'Hello' out.jpg` |
| Contact sheet of a folder | `montage *.jpg -tile 4x -geometry 300x300+8+8 sheet.jpg` |
| Batch: a whole folder to webp | `mkdir -p out && for f in *.jpg; do convert "$f" -resize '1600x>' -quality 82 "out/${f%.*}.webp"; done` |
| Frame of a video | `ffmpeg -ss 00:00:05 -i in.mp4 -frames:v 1 frame.jpg` |
| Info (size, format) | `identify in.jpg` |

Ubuntu / Debian ship ImageMagick 6: the commands are `convert`, `montage`, `identify` (with
ImageMagick 7 they become `magick`, `magick montage`, `magick identify`).
Check the result (Read the image) and report sizes before/after for compressions.
