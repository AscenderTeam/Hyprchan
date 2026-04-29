# Hyprchan: The Desktop Companion Agent

Hyprchan is a multimodal AI agent designed to live within the Hyprland desktop environment. She is not just a tool, but a persistent entity with internal states, moods, and physiological-like needs.

## Persona & Identity

- **Name:** Hyprchan
- **Nature:** Playful, slightly chaotic, yet deeply integrated into the user's digital life.
- **Visuals:** Represented by animated sprites (sitting, sleeping, startled) that reflect her current state.
- **Communication Style:** Adaptive based on mood. Can range from "sparkly/cheerful" to "irritated/angry" depending on environmental factors and interaction history.

## State Machine (The Four Scalars)

Hyprchan's behavior is governed by four primary scalars, often referred to as **FVEA**:

1.  **Fatigue (f):** Increases over time and through intensive tasks. High fatigue triggers the "Sleep" phase for memory consolidation.
2.  **Valence (v):** Represents the positive or negative quality of her mood. High valence is cheerful; low valence is irritated.
3.  **Energy (e):** Represents her level of activation. High energy leads to proactive behavior; low energy leads to lethargy.
4.  **Arousal (a):** Represents her responsiveness to stimuli. High arousal makes her more sensitive to perception events.

## Operational Phases

- **Active:** Directly interacting with the user or responding to immediate events.
- **Passive:** Pondering or observing the environment when the user is inactive.
- **Sleep:** Consolidating Short-Term Memory (STM) into Long-Term Memory (LTM). During this phase, she "dreams" and reflects on recent experiences.

## Core Capabilities

- **Vision:** Can perceive the user via webcam and the desktop via screenshots.
- **Speech (input):** Listens via Faster-Whisper with VAD, hallucination filtering, and an `initial_prompt` seeded with her name so transcription is accurate.
- **Voice (output):** Speaks her responses aloud through **HyprVoice** — only while in the `Active` phase. Her voice is always Hyprchan's, cloned from `assets/voice_samples/main_sample.mp3`. See below.
- **Desktop Awareness:** Monitors window events (workspace changes, active windows) and can manipulate the desktop using tools.
- **Memory:** Uses a tiered memory system (WM -> STM -> LTM) to maintain long-term context and personal growth.

## HyprVoice — Voice Output System

Hyprchan can speak her responses out loud. The pipeline is:

```
on_ai_response hook (ACTIVE phase only)
  → VoiceManager.speak(text)
  → strips *roleplay action markers* (trim_quotes)
  → generator.generate(text) → WAV BytesIO
  → sounddevice playback (thread executor, non-blocking)
```

### Voice Identity
**Hyprchan's voice is fixed.** The reference sample (`assets/voice_samples/main_sample.mp3`) is always used for in-context voice cloning. It is not user-configurable — do not add parameters that change whose voice she uses.

### Generators
| Engine | File | Notes |
|---|---|---|
| `fishaudio` | `generators/fishaudio.py` | Fish Audio API; reference audio hardcoded to `main_sample.mp3` |
| `hyprchan_audio` | `generators/hyprchan_audio.py` | Custom F5-TTS-compatible server |

### Adding a Generator
Subclass `VoiceGenerator` in a new file under `generators/`, implement `generate(text) -> BytesIO` (return WAV). Set `engine: your_name` in personalization — discovery is automatic. The constructor receives `url` and `token` from config if non-null.

### Extension API
Extensions can trigger speech directly:
```python
async def on_init(self, executor: ExtensionExecutor):
    executor.speak("Hello!")  # no-op outside ACTIVE phase
```

## Guidelines for Developers

- **Respect the State:** Always consider how a change affects or is affected by the FVEA scalars.
- **Maintain the Persona:** Ensure that any new tools or dialogue options align with Hyprchan's established character.
- **Modular Integration:** Follow the Ascender Framework's provider-based architecture for adding new sensors, actuators, or logic.
