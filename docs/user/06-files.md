---
section: Using Harness Maxxing
---
# Files

The **Files** page browses the server from the *files root* (Settings -> General, default `/root`).
Nothing outside that folder is reachable from the UI.

## Browse

- Breadcrumbs at the top, folders first, then files with size and date.
- Search finds files and folders by name in the workspace.
- Drag files from your computer onto the page to **upload** them into the current folder - or
  onto a folder row to upload them straight into that folder. One upload is limited to 2 GB, and
  the server refuses an upload that would leave less than 1 GB free on its disk ("Not enough free disk
  space"). Both limits are `upload_max_mb` and `upload_min_free_mb` in
  `/var/lib/claude-maxxing/config.json` (`upload_max_mb: 0` removes the size limit; no restart needed).
- Drag a file or folder onto another folder (or onto a folder of the breadcrumb at the top) to
  **move** it there. Desktop browsers only; on a phone use *Rename / move* in the item menu.

## Preview

Almost every file opens in a preview. Thumbnails (images, videos, first page of PDFs) need `ffmpeg` and
`pdftoppm` (installed by the installer).

| File | What you see |
|---|---|
| Images (also TIFF, converted on the fly) | the picture, zoomable |
| Videos, audio | the built-in player; videos have a **quality** button (Auto, Original, 1080p, 720p, 480p, see below) |
| PDF | the document (some phone browsers only offer *Open in a new tab*) |
| Markdown | rendered, or the source |
| CSV / TSV | a **table**: click a column to sort, filter rows, numbers right-aligned |
| HTML | the **page itself** with its images, styles and scripts (see below), or the source |
| Archives (zip, tar, tar.gz, gz) | the **list of what is inside**, with sizes, without extracting anything |
| Fonts (woff, woff2, ttf, otf) | a **specimen** in several sizes, with your own sample text |
| Code, text | highlighted, with line numbers |
| Anything else (Office documents, 7z, rar...) | a card with **Download** |

**Text size and where you were.** Markdown (rendered or source), code and text files have **− 100% +** in the
toolbar (on the Files page of a smaller window, or on a phone, the **T** button opens it): the text gets larger or
smaller and the passage you are reading stays in place; click the percentage to go back to 100%. Ctrl/⌘ + wheel
(or a trackpad pinch) over the text does the same. The size is kept in this browser. Each text file also remembers
where you were: switching **Preview**, **Edit** and **Split**, or opening the file again (even after a reload),
brings you back to the same passage.

**Video quality**: a big video (over 1080p, a high bitrate, or a format some browsers cannot play, like AV1 on
Safari) can be slow to start, mostly on a phone. The player's quality button (next to the speed) lists
**Auto**, **Original** and lighter copies. The server makes a copy once (H.264, built to start playing
at once), one video at a time and at low priority. Meanwhile the original keeps playing. A quality you pick switches
at the same moment when its copy is ready. **Auto** (the default) uses a 720p copy only for heavy videos, and only
once you press play: opening a video to look at it starts no encoding. With **Auto**, a copy that gets ready while
the original already plays well is kept for the next time you open the video (switching would make the picture jump);
it takes over at once only if the original keeps stalling or dropping frames.
Your choice is remembered on this device. Copies are kept up to 4 GB in total (the least recently played go first)
and need `ffmpeg`.

**HTML pages run isolated**: they get their own sandbox, separate from Harness Maxxing. Their scripts run,
but they cannot use your session, read the API or your cookies. Links that open a new tab or window keep
that sandbox (a site opened this way may ask you to open it directly to sign in). Relative images, styles, scripts,
fonts, audio and video next to the page (and in its sub-folders) load normally; data and documents do not (`.json`,
`.csv`, `.txt`, `.md`, `.pdf`...: a page cannot read your notes or exports next to it - inline the data in the page or
in a `.js` file instead). The link is valid for 2 hours and ends when you sign out: reopen the file after that.

**← / →** (or the arrows in the toolbar) go to the previous / next file of the folder - any type, not only
pictures. The **fullscreen** button opens the file viewer (see below) on the files of the folder.

- **Images** appear at once (thumbnail first, then a light version of large pictures); the full
  original loads quietly right after, so zooming (+, -, 0, double-click, the mouse wheel) stays
  instant. The wheel zooms by 5 % around the pointer (Shift + wheel scrolls); a zoomed image is moved by
  dragging it (the hand).
- **Videos and audio** play in the built-in player; click it, then: Space or K play/pause, ←/→ 5 s, J/L 10 s, ↑/↓
  volume, M mute, F full screen, 0-9 jump to 0-90 %, < / > slower / faster; the speed and quality buttons open
  the device's own list (the system picker on a phone, never cut off, also in full screen), speeds 0.5× to 4×;
  picture in picture and full screen from the buttons. The poster image appears at once. On a phone or a tablet,
  tap the speaker to show the volume slider, tap it again to mute (on an iPhone or iPad the slider also works,
  on top of the device's volume buttons).

## The file viewer

Files clicked in a session (attachments, pictures, files Claude read or wrote, paths in its answers) open
in the **file viewer**, a side panel - or fullscreen with its button (remembered; always fullscreen on a
phone).

- **← / →**, the arrows in its bar, or a **swipe** on a phone: previous / next file **of the
  conversation**, in reading order. The next ones are preloaded.
- A **diagram** of an answer opens here too: fitted to the window, **+ / -** or the wheel (5 % per notch) to zoom, drag to move
  around, double-click to switch between fitted and enlarged, **Source** for its code.
- A **folder** opens as a grid with thumbnails; click a file to open it, then ← / → browse that folder.
  **Parent folder** goes one level up.
- **Edit** (text files: markdown, txt, code, CSV, HTML) opens the file in the Files page, ready to edit - in a new
  tab on a computer, in place on a phone.
- **Open in Files** opens the file in the Files page - a new tab on a computer (the viewer stays open), in place
  on a phone.
- **Download** (pictures and PDFs on screen are saved at once, without downloading them again), **Esc** to close.

## Edit

Text files up to 2 MB open in an editor with syntax highlighting. Markdown, CSV and HTML have **Preview / Edit / Split** (the HTML preview shows the saved file). **Save** checks that the file
did not change on disk meanwhile (for example because Claude edited it): if it did, you get a
conflict warning instead of overwriting the other change. Reload, then re-apply your edit.

## Rename, move, delete, download

- Rename and move from the item menu.
- **Delete moves to the trash**: Settings -> **Trash** lists what was deleted (files, folders,
  topics and projects with their sessions, sessions) - **Restore** puts it back where it was (under a new name
  such as `blog-restored` when the place is taken; a long name is shortened to make room),
  *Delete forever* or *Empty the trash* frees the space. Items older than 30 days are removed
  automatically.
- The workspace folder itself (and the folders that hold it) cannot be moved or deleted from here,
  and a topic folder with a running session cannot be moved or deleted until that session is stopped
  (the same rule as the workspace sidebar).
- Download any file; large files are streamed.

## Tips

- Attachments sent in sessions and from Telegram live in `<topic>/attachments/`.
- A file path printed by Claude in a session is clickable and opens in the file viewer.
