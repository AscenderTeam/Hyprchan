# Hyprchan Development Guide (CLAUDE.md)

Hyprchan is a multimodal AI agent for the Hyprland desktop environment, built on the **Ascender Framework**.

## Technical Architecture

### Core Framework (Ascender)
- **FastAPI-based:** Modular, scalable, and asynchronous.
- **Provider Pattern:** Most services are abstracted as `providers` (e.g., `RedisProvider`, `EmbeddingProvider`).
- **Dependency Injection:** Centralized in `src/bootstrap.py`.

### State & Logic (FVEA)
The kernel loop (`src/core/hypraios/kernel/kernel.py`) is the brain of the system, managing:
- **Fatigue (f):** Governs transitions to the `Sleep` phase.
- **Valence (v) & Energy (e):** Dynamically affect LLM behavior through mood profiles and `logit_bias`.
- **Arousal (a):** Controls sensitivity to perception triggers.

### Perception Sources
- **Vision:** OpenCV-based (`WEBCAM_VISION_ENABLED`).
- **Speech:** Whisper-based (`SPEECH_PERCEPTION_ENABLED`).
- **Communication:** Web-based events and user messages.

### Memory System (STM/LTM)
- **WM (Working Memory):** Transient state and recent turns.
- **STM (Short-Term Memory):** Narrative event log.
- **LTM (Long-Term Memory):** Semantic store using pgvector or SQLite.
- **Consolidation:** Occurs during the `Sleep` phase via `src/core/hyprmemory/consolidation/sleep_consolidator.py`.

## Voice Output (HyprVoice)

### Architecture
- `src/core/hyprvoice/generator.py` — `VoiceGenerator` ABC: `generate(text) -> BytesIO`, `stream()`, `stop()`
- `src/core/hyprvoice/generators/` — one file per engine, class name auto-discovered via importlib
  - `hyprchan_audio.py` — `HyprchanAudioGenerator`: multipart POST to a custom F5-TTS-compatible endpoint
  - `fishaudio.py` — `FishAudioGenerator`: Fish Audio API (`https://api.fish.audio/v1/tts`), always sends `main_sample.mp3` as the in-context reference — Hyprchan's voice is hardcoded, not configurable
- `src/core/hyprvoice/manager.py` — `VoiceManager`: loads the generator, plays WAV via sounddevice in a thread executor, fires-and-forgets per response
- `src/core/hyprvoice/utils.py` — `get_sample_voice_path()` → `src/hyprchan/assets/voice_samples/main_sample.mp3`

### Kernel Integration
`VoiceManager` is instantiated in `HyprAIOSKernel.__init__`, `setup()` is called in `bootup()`, and an `on_ai_response` hook fires `speak(output, phase=phase)` — **speech only triggers in `ACTIVE` phase**.

### Personalization Config (`voice:` section)
```yaml
voice:
  enabled: true
  engine: fishaudio          # or hyprchan_audio
  token: "your-api-key"      # SPEECH_TOKEN env var also works
  url: "https://..."         # optional; fishaudio defaults to api.fish.audio
  trim_quotes: true          # strips *roleplay action markers* before TTS
  device: null               # sounddevice output device (null = system default)
  sample_rate: 22050
```
Env overrides: `HYPRCHAN_VOICE_ENABLED`, `HYPRCHAN_VOICE_ENGINE`, `HYPRCHAN_VOICE_URL`, `SPEECH_TOKEN`, `HYPRCHAN_VOICE_TRIM_QUOTES`, `HYPRCHAN_VOICE_DEVICE`.

### Adding a New Generator
1. Create `src/core/hyprvoice/generators/<engine_name>.py`
2. Subclass `VoiceGenerator`, implement `generate(text) -> BytesIO` returning WAV bytes
3. Set `engine: <engine_name>` in personalization — the manager discovers it automatically
4. Constructor kwargs `url` and `token` are forwarded automatically if the field is non-null in config

### Extension API
```python
executor.speak("Hello!")  # fires only when kernel is ACTIVE, respects trim_quotes
```

## Key Development Commands

### Environment Setup
```bash
poetry install
poetry shell
```

### Running the Project
- **Full System:** `ascender run serve`
- **Rich TUI (CLI Interface):** `python src/hypraios_tui.py --model gpt-4o-mini`
- **Speech Debug CLI:** `python src/speech_debug_cli.py`

### Testing
```bash
pytest
```

## Project Structure
- `src/core/hypraios/`: Primary kernel, linguistic engine, and mood system.
- `src/core/hyprmemory/`: Memory layers (WM/STM/LTM) and consolidation logic.
- `src/core/hyprland/`: IPC and socket management for Hyprland integration.
- `src/animations/`: Pose definitions and animation sets.
- `src/controllers/v1/`: API and event routers.
- `src/shared/`: Shared utilities and database runtimes.

## Coding Conventions
- **Asynchronous First:** Use `async`/`await` for I/O-bound operations.
- **Provider-Based:** When adding new services, implement them as providers and register them in `bootstrap.py`.
- **State Sensitivity:** Logic should ideally be "state-aware" (responding differently based on FVEA).
- **Atomic Commits:** Prefer small, surgical, and well-described git commits.
