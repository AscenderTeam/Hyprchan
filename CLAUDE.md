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
