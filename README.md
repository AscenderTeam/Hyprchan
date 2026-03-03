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

## OpenAI OAuth Setup

HyprAI OS now uses OpenAI bearer-token authorization (OAuth style) for inference.

Create a `.env` file in the project root with:

```bash
OPENAI_OAUTH_TOKEN=your_oauth_bearer_token
# or OPENAI_API_KEY=... as fallback
OPENAI_MODEL=gpt-4o-mini
OPENAI_API_BASE_URL=https://api.openai.com/v1
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
WEBCAM_AUTO_INSTALL_OPENCV=true
WEBCAM_AUTO_FIND_DEVICE=true
WEBCAM_MAX_DEVICE_INDEX=4
MULTIMODAL_SNAPSHOT_ENABLED=true
MULTIMODAL_SNAPSHOT_INTERVAL_SEC=120
SPEECH_PERCEPTION_ENABLED=true
SPEECH_INPUT_DEVICE=
SPEECH_LANGUAGE=en
SPEECH_FRAME_DURATION_MS=30
SPEECH_MIN_SPEECH_SEC=0.4
SPEECH_END_SILENCE_SEC=0.8
SPEECH_MAX_SPEECH_SEC=15
SPEECH_PRE_ROLL_SEC=0.3
SPEECH_MIN_START_DBFS=-38
SPEECH_MIN_CONTINUE_DBFS=-43
```

API endpoints:

- `GET /v1/events/vision/status`
- `GET /v1/events/vision/scan`
- `GET /v1/events/speech/status`

## Web Communication Source

Serve mode now includes a user communication perception source and event feed:

- `GET /v1/communication` - HTML communication client.
- `POST /v1/communication/send` - send user text as a perception event (`communication_controller`).
- `GET /v1/communication/events` - view all events and agent responses.

Core behavior:

- Non-user perception sources are buffered into context and event logs.
- User-origin events trigger inference immediately.
- Passive pondering runs in core kernel after 40s of no user communication.
- Every 2 minutes, a PerceptionSource captures a full-screen image (downscaled x2) and latest webcam frame; both are attached as multimodal content on subsequent inferences.
- Snapshot files are written under `runtime/perception/`.
- A speech PerceptionSource continuously listens on default microphone (or `SPEECH_INPUT_DEVICE` override), detects utterances by volume + silence boundaries, and emits them as `communication_controller` events to trigger immediate inference.

Speech debug CLI:

```bash
python src/speech_debug_cli.py --list-devices
python src/speech_debug_cli.py
python src/speech_debug_cli.py --device "USB" --no-transcribe
```

Agent context persistence:

- Context, event logs, responses, and persona memory are saved to `agent_memory.json` at repository root and reloaded on boot.

## LLM Animation Tools

HyprAI OS inference now exposes LangChain tools for the overlay renderer:

- `set_animation_pose` - picks one loaded pose from the current animation set.
- `move_self` - moves Hyprchan by directional delta and sets sprite scale coefficient in range `0..2`.
- `screenshot` - captures a live screenshot and returns it as multimodal tool output.
- `camera` - captures a live webcam photo and returns it as multimodal tool output.
- `answer_user` - renders user-facing text in white on top of Hyprchan figure.

Tool multimodal outputs are persisted into context/event history as `tool_observation` events before the assistant reply is saved, so image evidence remains recallable in later turns.

If the model returns plain text without calling `answer_user`, HyprAI OS mirrors that text to the overlay automatically.
