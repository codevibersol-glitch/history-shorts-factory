# 🏛️ History Shorts Factory

**Fully automated AI-powered YouTube Shorts generator for history content.**

Give it a topic → get a ready-to-upload Short in minutes.

---

## How It Works

```
Topic
  ↓
Grok (grok-4-1-fast-reasoning) writes a ~155-word historically accurate script
  ↓
edge-tts (Microsoft Neural voices) narrates the script → MP3
  ↓
Grok Imagine generates 4–5 cinematic 9:16 video clips
  ↓
ffmpeg assembles: video loops to fill full narrator duration + audio muxed
  ↓
Final Short ready (optionally auto-uploads to YouTube)
```

---

## Features

- **AI Script Writing** — Grok reasons over Wikipedia source material to extract the most incredible, verified historical facts. Short punchy sentences, shocking hook, strong ending.
- **Cinematic Video** — Grok Imagine generates era-accurate BBC/Netflix-style footage. Intro clip gets a title card; subsequent clips cycle through battle action, key figures, aftermath, and artifacts.
- **Natural Narration** — Microsoft edge-tts with Christopher Neural voice. No API key, no cost, runs locally.
- **Smart Assembly** — ffmpeg scales video to 1080×1920, loops it to match narrator length, muxes TTS audio. Zero silent gaps.
- **YouTube Upload** — Optional direct upload with title, description, tags, and thumbnail.

---

## Setup

### 1. Clone & install

```bash
git clone https://github.com/YOUR_USERNAME/history-shorts-factory
cd history-shorts-factory
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure

```bash
cp .env.example .env
```

Edit `.env` and add your keys:

```env
XAI_API_KEY=your_xai_api_key_here           # xAI API — for Grok script + Grok Imagine video
YOUTUBE_CLIENT_SECRETS=client_secrets.json  # optional — only needed for YouTube upload
```

Get your xAI API key at [console.x.ai](https://console.x.ai)

### 3. Run

```bash
# Generate a Short (Grok Imagine video + edge-tts audio)
python history_shorts.py run --topic "Battle of Waterloo" --use-grok-imagine

# Generate + upload to YouTube
python history_shorts.py run --topic "Six-Day War" --use-grok-imagine --upload

# Get topic suggestions
python history_shorts.py suggest-topics
```

---

## Requirements

- Python 3.10+
- ffmpeg installed (`brew install ffmpeg` on macOS)
- xAI API key (for Grok script generation + Grok Imagine video)
- YouTube API credentials (optional, only for auto-upload)

---

## Output

Each run produces in `output/`:
- `grok_<topic>_<timestamp>.mp4` — raw Grok Imagine clips (video only)
- `audio_<topic>_<timestamp>.mp3` — edge-tts narration
- `subtitles_<topic>_<timestamp>.srt` — subtitle timings
- `history_short_<topic>_<timestamp>.mp4` — **final assembled Short**

---

## Stack

| Component | Technology |
|-----------|-----------|
| Script writing | Grok `grok-4-1-fast-reasoning` via xAI API |
| Video generation | Grok Imagine (`grok-imagine-video`) |
| Text-to-speech | [edge-tts](https://github.com/rany2/edge-tts) — Microsoft Neural voices, free |
| Video assembly | ffmpeg |
| Wikipedia research | `wikipedia` Python library |
| YouTube upload | YouTube Data API v3 |

---

## Environment Variables

See [`.env.example`](.env.example) for all options.

| Variable | Required | Description |
|----------|----------|-------------|
| `XAI_API_KEY` | ✅ | xAI API key for Grok script + video |
| `YOUTUBE_CLIENT_SECRETS` | Optional | Path to YouTube OAuth credentials |
| `TTS_VOICE` | Optional | edge-tts voice (default: `en-US-ChristopherNeural`) |
| `VIDEO_DURATION` | Optional | Target duration in seconds (default: `55`) |
| `GROK_SCRIPT_MODEL` | Optional | Grok text model (default: `grok-4-1-fast-reasoning`) |

---

## License

MIT
