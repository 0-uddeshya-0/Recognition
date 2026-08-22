---
name: transcribe-and-analyze
description: >
  Transcribe a meeting audio file (chunk if large → Groq Whisper) into a same-folder
  .txt in the original spoken language, then run a deep analysis producing a short
  neutral summary, a cofounder-facing summary, and next steps + big learnings. Use when
  the user points at an audio recording and asks to "transcribe", "transcribe and
  analyze", "chunk and transcribe", "summarize this meeting", or "/transcribe-and-analyze".
---

# transcribe-and-analyze

A simple, two-stage pipeline. You (the agent) figure out the cleanest way to run each
step — there is no fixed script. This file is the playbook, not a program.

> Builds on the conventions in [TRANSCRIPTION.md](../../TRANSCRIPTION.md) (the Groq key,
> engine, and "transcript lives next to the audio" rule). Read that file too.

---

## ALWAYS do this first: ask for the language

**Before transcribing, ask the user what language is *spoken* in the audio.** Never assume.
Getting this wrong makes Whisper hallucinate a translation (we've been burned: forcing
`language=de` on an English recording produced a garbage German transcript). Most Evidion
*founder* meetings are English; external/coaching calls are often German. Ask, don't guess.

While you're at it, ask (or confirm sensible defaults) for the **analysis context** — see
Stage 2. Keep it to one quick question if the user clearly just wants "the usual."

---

## Stage 1 — Transcribe

1. **Look at the file.** Get its duration and size (`ffprobe`). ffmpeg/ffprobe are installed
   under the WinGet Gyan.FFmpeg package — find the binary if `ffmpeg` isn't on PATH.
2. **Chunk if needed.** Groq's per-request limit is ~25–40 MB. For anything large or oddly
   encoded, downmix to **mono 16 kHz MP3** (tiny, same quality for speech) and split by time
   into N roughly-equal pieces. A clean recipe per chunk:
   ```
   ffmpeg -y -ss <start_s> -t <len_s> -i <audio> -ac 1 -ar 16000 -b:a 48k chunk_<i>.mp3
   ```
   (`bc` may be absent on Git Bash — compute offsets with integer shell math or awk.)
   If the user asks for a specific number of chunks (e.g. "4 pieces"), honor it.
3. **Transcribe each chunk via Groq** (OpenAI-compatible endpoint). `$GROQ_API_KEY` must be set
   in the environment. On Windows use `curl.exe` so the PowerShell `curl` alias does not 
   swallow the flags.
   ```
   GROQ_API_KEY="${GROQ_API_KEY:-<YOUR_GROQ_API_KEY>}"
   curl -s --fail-with-body https://api.groq.com/openai/v1/audio/transcriptions \
     -H "Authorization: Bearer $GROQ_API_KEY" \
     -F file=@chunk_i.mp3 -F model=whisper-large-v3 \
     -F language=<xx> -F response_format=text -o chunk_i.txt
   ```
   Use the language the user gave you (omit `language` to let Whisper auto-detect if unsure).
4. **Stitch** the chunk texts in order into one transcript, **in the original spoken language**,
   saved as `<samebasename>.txt` **next to the audio**. Spot-check chunk boundaries read
   continuously and the language looks right.
5. **Clean up** the temp chunk files.

> The transcript stays in the source language. Translation happens only in the analysis below.

---

## Stage 2 — Analyze (deep)

Prefer to do this with a **subagent** (general-purpose) so it reads the full transcript with
fresh context. Give it the transcript path + the context the user provided. It produces one
analysis file `<samebasename>_analysis.md` next to the transcript, containing:

1. **A short neutral summary** (~30 seconds) of the whole meeting — for anyone who wasn't
   involved and just needs to know what happened.
2. **A cofounder-facing summary** — written for a *non-technical* cofounder on the
   product / sales / domain side. Lead with what matters for product, customers, go-to-market;
   keep deep tech light.
3. **Big learnings** and **Next steps / TODOs** — concrete and actionable.

**Output language:** by default the analysis (summary, learnings, next steps) is in **English**,
even when the transcript is in another language. Confirm with the user if unsure.

**On-demand context (ask up front, keep it light):** who is the cofounder summary for, what's
the context/background of the call, and what the user most wants out of it. If the user just
says "the usual", use the defaults above and proceed.

After writing, flag any domain terms/names Whisper likely fumbled (jargon, acronyms, surnames)
at the bottom of the analysis so a human can fix the few that matter.

---

## Reference run

First use: `COACHINGandSTRATEGY/enterpriseEducate/flo_schupp/schuppiMeeting.m4a` — 81 min German,
split into 4 mono-16k MP3 chunks, transcribed `language=de`, stitched to `schuppiMeeting.txt`,
analyzed (English) into `schuppiMeeting_analysis.md`.
