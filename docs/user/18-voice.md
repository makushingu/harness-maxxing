---
section: Connectivity
---
# Voice messages

Talk instead of typing - in the browser with the mic button, and from your phone with Telegram voice
notes. Claude cannot listen to audio, so your recording is first turned into text **on your server**;
the transcript is what Claude reads.

## Choose an engine (Settings -> Voice)

| Engine | Pros | Cons |
|---|---|---|
| **On this server** (Whisper, `faster-whisper`) | private (audio never leaves the server), free, no key | slower on small servers, ~0.5-1 GB RAM while in use, ~150-500 MB download |
| **Groq** (`whisper-large-v3-turbo`) | fastest and most accurate, about $0.04 per hour of audio | needs a `GROQ_API_KEY`, audio sent to Groq |
| **OpenAI** (`gpt-4o-mini-transcribe`) | accurate, about $0.18 per hour of audio | needs an `OPENAI_API_KEY`, audio sent to OpenAI |
| **Off** | - | no mic button; Telegram voice notes get a short hint |

API keys are stored in the Keys vault (you can paste them directly in Settings -> Voice).

### Local engine: models and speed
Pick the model in Settings -> Voice, then **Install / Download** (runs in the background, with
progress; you can leave the page). Without a download, the first voice message downloads the model.

| Model | Download | Notes |
|---|---|---|
| tiny | ~75 MB | very fast, rough |
| base | ~145 MB | default on servers with less than 4 GB RAM - good for English, ok for other languages |
| small | ~485 MB | **default** - very good in English and French |
| medium | ~1.5 GB | best, needs 2+ GB free RAM and patience on small CPUs |

Order of magnitude on 2 vCPUs: a 1-minute message takes ~15 s with `base`, ~30-60 s with `small`
(faster with more cores). The model stays in memory for 10 minutes after the last message, then is
unloaded. One message is transcribed at a time; the others wait their turn.

**Language:** automatic detection works well for normal speech. Fix the language (Settings -> Voice ->
Language) if you always speak the same one, or for very short or noisy notes.

## In the browser
- The **mic button** sits next to *Send* in every session and in an agent's conversation (the same voice
  messages; in an agent group, the transcript is put in the box). You do not use it? Settings -> Voice ->
  **Buttons of the message box** hides the mic button and the voice mode button, from every message box on every
  device.
- **Tap** to start, tap ✓ to stop; or **hold** to talk and release to stop (push-to-talk). Slide left
  while holding, press **Esc** or ✕ to cancel.
- **When you stop, the voice message is sent right away**, like on Telegram: it appears in the
  conversation as one bubble: a round mic button (tap it to listen to the recording, again to pause)
  and, next to it, the transcript once the server has made it; the transcript then goes to Claude. You can keep talking or typing meanwhile: the next messages wait their turn.
  The recording is saved in the topic (`attachments/YYYY-MM/voice-….webm`).
- Prefer to read the text before sending? Turn off **Settings -> Voice -> Send voice messages right
  away**: the transcript is then inserted at the cursor so you can fix it, or sent as text with
  **Send automatically**.
- If the transcription fails (or nothing was heard), the recording stays in the conversation and
  nothing is sent to Claude; send it again or type your message.
- Browsers only give access to the microphone on **HTTPS** pages (or `localhost`). With a domain
  (Caddy) it just works; over plain `http://<tailscale-ip>` it does not - use an HTTPS access mode or
  an SSH tunnel to `localhost`.
- Works on iPhone (Safari) and Android (Chrome). Allow the microphone when the browser asks; if you
  refused once, re-allow it in the site settings (the lock icon in the address bar).
- Several microphones (a headset, a USB microphone)? **Settings -> Voice -> Microphone** chooses the one that
  records on this device; browsers show their names once the microphone is allowed (**Show the microphones**).
  The choice stays in this browser, and the default microphone records while the chosen one is unplugged.
- Recordings are limited to 15 minutes.
- **Record a test** in Settings -> Voice shows the transcript, the detected language and the time it
  took.

## On Telegram
Send a **voice note** or a **round video note** in a session thread (an audio file sent as a file - music, a recording - is passed as an attachment, not transcribed):
1. the bot replies with `🎤 <transcript>`,
2. the transcript is sent to the topic's session as your message (the audio file is attached, saved
   under `<topic>/attachments/voice/YYYY-MM/`),
3. Claude answers as usual.

If voice messages are off, the bot replies with a short hint instead.

## Voice mode (talk with Harness)
The **voice mode** button (sound waves, in the bar of a session, or next to *Send* on an agent's page) starts a call. A voice answers you at once and
talks with you; anything real (look something up, check, change, create...) it hands to the session - the same
Claude, with its files and tools - **in your own words**, and tells you the outcome when the session is done.
Everything handed over appears in the session as your messages, so nothing happens out of sight.

- **While it works**, keep talking: ask where it is at, or add something ("also check the blog"): what you add
  joins the work in progress. Now and then the voice tells you what it is doing. Say **"stop"** to stop the work.
- **One language per call**: the one of your first sentence. It changes when you ask ("speak English") or when you
  clearly speak another language.
- **Cut the voice by speaking**: as soon as you speak it lowers its volume; once it is sure it is you (under a
  second of real speech) it stops and listens to the end. If it was only noise, its own echo or a mere "yeah", it
  says its sentence again. While you speak it says nothing new: what you add joins what you said before and gets one
  answer. **Tapping the call** cuts it too.
- **Pause before your sentence ends** (Settings -> Voice -> Voice mode): how long a silence lasts before the voice
  answers (1.8 s by default; raise it if you get cut while thinking).
- A short rising tone tells you the call is connected, a falling one that it ended.
- **Hang up** with the red button.
- **Settings -> Voice -> Voice mode** also chooses the voice:
  - **On this server** (default): free and private. It hears you with the engine above, talks with a Claude model
    (Sonnet by default: better decisions; Haiku answers faster) and speaks with Piper (install it from the card:
    about 150 MB). Choose its **voice** (several French and English voices, each downloaded when chosen) and its
    **speed**.
  - **Cloud (realtime)**: OpenAI Realtime or Gemini Live, under a second, very natural, about 1 to 5 cents a minute
    on your own key, with the same rules. Harness finds the keys in the Keys vault (`OPENAI_API_KEY`,
    `GEMINI_API_KEY`, or any key whose name contains OPENAI / GEMINI) and asks which one to use when there are
    several. Your key never leaves the server: each call gets a short-lived token. The audio goes to that provider.
    A long call goes on by itself when the provider renews its connection (Gemini every 10 minutes or so), and
    tapping the call cuts the voice for good.

## From the terminal
```
maxxing voice status                 # engine, model, readiness
maxxing voice set --engine local --model small --language auto
maxxing voice download [model]       # pre-download a local model
maxxing voice transcribe note.ogg    # test a file
```
`maxxing doctor` reports the voice status. To install the local engine by hand:
`cd /opt/claude-maxxing/server && uv sync --extra voice` (then `maxxing update` keeps it).

## Troubleshooting
- *Mic button greyed out* - voice is off or not ready: open Settings -> Voice.
- *"Browsers only allow the microphone on HTTPS pages"* - see above.
- *"ffmpeg is missing"* - `apt-get install -y ffmpeg`.
- *Wrong language / gibberish* - fix the language, or use a bigger model.
- *Slow* - use `base`, or switch to Groq.
