# Ascender Framework Project

## Overview

This project is built using the **Ascender Framework**, a structured FastAPI-based framework designed for modular and scalable applications.

---

## Getting Started

### Prerequisites

Ensure you have the following dependencies installed:

- **Python 3.11 or higher**
- **Poetry** (for dependency management)
- **pip** (Python's package manager)

### Installation

1. **Install Poetry** (if not already installed):

   ```bash
   pip install poetry
   ```

2. **Configure Poetry to use virtual environments**:

   ```bash
   poetry config virtualenvs.create true
   ```

3. **Install project dependencies**:

   ```bash
   poetry install
   ```

4. **Run development server**:
    
    ```bash
    ascender run serve
    ```

If everything works, you're done!

## OpenAI GPT-5.3 OAuth Setup

HyprAI OS now uses OpenAI bearer-token authorization (OAuth style) for inference.

Create a `.env` file in the project root with:

```bash
OPENAI_OAUTH_TOKEN=your_oauth_bearer_token
# or OPENAI_API_KEY=... as fallback
OPENAI_MODEL=openai/gpt-5.3
OPENAI_API_BASE_URL=https://api.openai.com
OPENAI_TIMEOUT_SECONDS=30
```

The kernel loop is booted by the window events service on startup. You can also force USER-active state via:

`GET /v1/summon`

## Rich Live TUI

Run the live Rich terminal interface with verbose state explanations:

```bash
python src/hypraios_tui.py --model gpt-4o-mini
```

Inside the TUI, commands are:

- `/help` for command help
- `/state` for an inline scalar snapshot
- `/memory` for recent narrative memory snapshot
- `/scroll <up|down|pageup|pagedown|top|bottom> [n]` to navigate chat history
- `/follow <on|off>` to toggle live auto-follow of new chat lines
- `/clear` to clear the chat log
- `/reset` to reset scalar state/context
- `/quit` to exit

The inference layer now applies dynamic token-level `logit_bias` derived from state scalars (`v`, `e`) using mood profiles (sparkly/cheerful/irritated/angry) with bounded intensity.

When fatigue reaches SLEEP, the TUI now shows a live memory-consolidation sequence with periodic one-way `<system>` telemetry and Hypr-chan dream/reflection outputs until consolidation completes.

## Webcam Perception (OpenCV)

HyprAI OS can read your webcam feed as a perception source and emit raw events for face presence and motion.

Env toggles:

```bash
WEBCAM_VISION_ENABLED=true
WEBCAM_DEVICE_INDEX=0
WEBCAM_POLL_INTERVAL_SEC=0.25
WEBCAM_MIN_MOTION_RATIO=0.02
WEBCAM_MIN_FACE_RATIO=0.002
WEBCAM_MIN_EMIT_INTERVAL_SEC=1.2
```

API endpoints:

- `GET /v1/events/vision/status`
- `GET /v1/events/vision/scan`
