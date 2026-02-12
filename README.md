# Comic Chaos

An interactive AI-powered comic strip generator. Pick a comic series, fill in the speech bubbles, and watch the story unfold — panel by panel.

Comic Chaos uses OpenAI's language and image models to orchestrate narrative, generate artwork, detect speech bubbles, and render text — all in real time through a streaming web interface.

## Features

- **Interactive storytelling** — You drive the narrative by filling in speech bubbles, thought bubbles, and narration boxes. The AI builds on your input to advance the story.
- **AI-generated artwork** — Each panel is generated as a unique comic illustration with streaming partial previews.
- **Smart bubble detection** — OpenCV detects empty speech bubbles and narration boxes in generated images, placing your text precisely inside them.
- **Multiple comic series** — Each comic has its own blueprint defining characters, locations, visual style, and narrative rules.
- **Bilingual support** — Full Norwegian (Bokmål) and English UI with per-comic translations.
- **Downloadable strips** — Finish your comic and download the assembled strip as a single PNG image.

## How It Works

```
User fills bubble → Narratron (LLM) generates next scene → Image model renders panel
     ↑                                                              ↓
     └──────────── OpenCV detects bubbles ← Text rendered in ←──────┘
```

1. **Narratron** — The LLM engine (GPT-4o-mini / GPT-4.1) orchestrates the story, maintaining narrative state, character consistency, and pacing.
2. **Image Generator** — OpenAI's image models generate comic panels with empty speech bubbles baked into the artwork.
3. **Panel Detector** — OpenCV contour detection finds bubble and narration box regions in the generated images.
4. **Text Renderer** — Pillow renders user text into detected bubble regions with auto-sizing and wrapping.
5. **Comic Strip** — All panels are composited into a final downloadable strip image.

## Quickstart

### Prerequisites

- Python 3.10+
- An [OpenAI API key](https://platform.openai.com/api-keys) with access to chat and image generation models

### Setup

```bash
# Clone the repository
git clone https://github.com/sbfroy/ComicChaos.git
cd ComicChaos

# Create and activate a virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure your API key
cp .env.example .env
# Edit .env and add your OpenAI API key

# Start the server
python main.py
```

Open [http://localhost:5000](http://localhost:5000) in your browser.

## Project Structure

```
ComicChaos/
├── main.py                          # Entry point — starts Flask server
├── app.py                           # Flask routes and ComicSession logic
├── requirements.txt                 # Python dependencies
├── .env.example                     # Environment variable template
│
├── src/
│   ├── config.py                    # Central configuration defaults
│   ├── prompt_loader.py             # Template loader for LLM prompts
│   ├── comic_strip.py              # Final strip assembly and text rendering
│   │
│   ├── narratron/
│   │   └── narratron.py            # LLM story orchestration engine
│   │
│   ├── image_gen/
│   │   ├── image_generator.py      # OpenAI image generation + streaming
│   │   ├── panel_detector.py       # OpenCV bubble/box detection
│   │   └── text_renderer.py        # Pillow text rendering into bubbles
│   │
│   ├── state/
│   │   ├── static_config.py        # Blueprint + comic config (Pydantic models)
│   │   └── comic_state.py          # Session state management
│   │
│   ├── prompts/
│   │   ├── narratron.system.md     # System prompt for the LLM
│   │   ├── panel.user.md           # Per-panel user prompt template
│   │   └── opening_sequence.user.md # Opening sequence prompt template
│   │
│   └── logging/
│       └── interaction_logger.py   # JSON logging of LLM interactions
│
├── comics/                          # Comic series definitions
│   ├── paul_the_panda/             # Each comic has:
│   │   ├── blueprint.json          #   Story definition (characters, locations, rules)
│   │   ├── blueprint.no.json       #   Norwegian translation (optional)
│   │   └── config.json             #   Model/rendering config overrides
│   └── superhero_simen/
│       └── ...
│
├── templates/
│   └── index.html                  # Single-page frontend (vanilla JS + SSE)
│
├── static/
│   ├── fonts/                      # Comic Neue font (OFL licensed)
│   └── images/                     # Logo and UI assets
```

## Creating a New Comic

Create a new directory under `comics/` with:

1. **`blueprint.json`** — Defines the comic world:
   ```json
   {
     "title": "My Comic",
     "synopsis": "A short hook for the story",
     "visual_style": "Describe the art style in detail",
     "locations": [
       {"name": "Starting Place", "description": "Where the story begins"}
     ],
     "characters": [
       {"name": "Hero", "description": "Visual description + personality"}
     ],
     "rules": ["Tone and behavior guidelines for the LLM"],
     "narrative_premise": "The thematic engine of the story"
   }
   ```

2. **`config.json`** (optional) — Override model settings:
   ```json
   {
     "llm_model": "gpt-4.1",
     "image_model": "gpt-image-1.5",
     "image_quality": "medium"
   }
   ```

3. **`blueprint.no.json`** (optional) — Norwegian translation of the blueprint.

The comic will automatically appear in the selection screen.

## Tech Stack

| Component | Technology |
|---|---|
| Backend | Python, Flask |
| Frontend | Vanilla JavaScript, Server-Sent Events |
| LLM | OpenAI GPT-4o-mini / GPT-4.1 |
| Image generation | OpenAI gpt-image-1 |
| Bubble detection | OpenCV |
| Text rendering | Pillow |
| Data models | Pydantic v2 |

## Roadmap

- [ ] Faster, higher-quality image generation
- [ ] Persistent sessions (database-backed instead of in-memory)
- [ ] User accounts and comic galleries
- [ ] More comic series
- [ ] Mobile-optimized UI

## Contributing

Contributions are welcome! To get started:

1. Fork the repo and create a feature branch from `main`
2. Install dev dependencies: `pip install ruff`
3. Make your changes — keep PRs focused and reasonably small
4. Run `ruff check .` before pushing
5. Open a PR against `main`

**Code style:** Python follows [Ruff](https://docs.astral.sh/ruff/) defaults (line length 120), use type hints for function signatures, and prefer Pydantic models for structured data. Frontend is vanilla JS in a single `index.html`.

**Adding a comic?** See [Creating a New Comic](#creating-a-new-comic) above — just add a new directory under `comics/` with a `blueprint.json`.

Found a bug or have an idea? Open an issue — no template needed, just describe it clearly.

## License

[MIT](LICENSE) — Copyright (c) 2026 Simen
