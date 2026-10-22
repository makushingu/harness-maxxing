# Project second-brain

Your personal knowledge system in plain Markdown: "note for today: long call with the bank, felt tired",
"what do I know about sleep?", "summarize this article and add it to my reading notes".

## Topics

- `journal`: daily notes (typed or voice), gratitude, lessons, mood and energy, the weekly review.
- `knowledge`: evergreen notes by subject, linked together, the answer to "what do I know about X?".
- `reading`: reading list, summaries of books, articles and videos, key ideas and quotes.
- `ideas`: inbox of raw ideas, tags, and a weekly triage into projects or tasks.

## Shared conventions

- Everything is plain Markdown inside the topic folders (`topics/<topic>/...`); no database. File
  names are lowercase with dashes (`topics/knowledge/deep-work.md`), dates are `YYYY-MM-DD`.
- Link notes with relative Markdown links (from a journal day: `../../knowledge/deep-work.md`), so
  they work in the Files page and in any Markdown editor.
- Files sent from the phone or the web arrive in the topic's `attachments/YYYY-MM/`; link them from
  the note that uses them. Voice notes arrive already transcribed: clean them up, keep the meaning.
- Who the user is and what they care about live in this project's `memory.md`; topic habits live
  in each topic's `memory.md`. Read both before working.
- Never delete or rewrite a note without asking; append instead. Keep the user's own words for
  journal entries and ideas, only fix obvious transcription errors.
- Follow-ups go to the task board (`maxxing-tasks` skill). Past conversations are searchable with
  Ctrl+K; the notes themselves can be searched with `grep -ri` in the project folder.

@memory.md
