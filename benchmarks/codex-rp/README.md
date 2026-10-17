# Codex dialogue latency experiment

These scripts run actual OpenAI inference through the installed local `codex app-server`, using the user's existing Codex sign-in. They do not use a local neural model. No packages need installing. All inference requests in each experiment are serial.

The benchmark starts an isolated temporary Codex home, links the existing authentication file without parsing or copying credentials, uses an empty temporary workspace and ephemeral threads, and deletes its temporary files at exit. The prompts and stored conversations are synthetic. Existing Hyprchan runtime configuration and memory are not loaded by the benchmark.

## Try the dialogue prototype

From the repository root:

```sh
node scripts/chat_codex_rp.mjs
```

The demo starts one persistent app-server, prepares one conversation with a hidden startup inference, then streams fresh generated replies. Wait for `Ready`, enter `hi`, and use `/quit` to exit. It prints measured first-text, last-text, and completed-turn times. There is no canned or cached greeting. This is a terminal prototype, not an integration into the desktop kernel, overlay, or speech pipeline.

The demo configuration is `gpt-6-luna`, `reasoning.effort=low`, and `service_tier=fast`. It had fewer deadline misses than GPT-5.6 Luna/none/priority across the equally sized expanded warm samples. Codex resolves `fast` to `priority`. Override the model, effort, or tier with `HYPRCHAN_CODEX_MODEL`, `HYPRCHAN_CODEX_EFFORT`, or `HYPRCHAN_CODEX_TIER`. Standard processing also performed well in smaller comparisons; priority was not consistently faster.

See [the measured results](REPORT.md) for the full table, deadline misses, and limitations. The demo's model choice does not imply a guaranteed two-second deadline.

## Reproduce the measurements

Use new output directories for every run; existing trial files are never overwritten or appended to by a new run.

```sh
# Discover models, then measure all picker-visible models and five RP scenarios.
node scripts/bench_codex_rp.mjs --trials=3

# Compare persistent threads, rotating configuration order between rounds.
node scripts/compare_codex_rp.mjs --variants=benchmarks/codex-rp/variants.json --rounds=5 --quality --out=/tmp/hyprchan-settings-new

# Twenty greetings, paired standard/priority tests, eight RP scenarios, real idle waits.
node scripts/verify_codex_rp.mjs /tmp/hyprchan-validation-new

# Repeat validation for the other small-model candidate.
HYPRCHAN_CODEX_MODEL=gpt-6-luna HYPRCHAN_CODEX_EFFORT=low node scripts/verify_codex_rp.mjs /tmp/hyprchan-luna6-new

# Check mood adaptation using the repository's actual scalar units.
node scripts/bench_codex_rp.mjs --models=gpt-5.6-luna --effort=none --trials=1 --cases=benchmarks/codex-rp/native-mood-cases.json

# Extract the current repository prompt, without starting the application.
python scripts/export_codex_rp_prompt.py
node scripts/bench_codex_rp.mjs --models=gpt-5.6-luna --effort=none --prompt=benchmarks/codex-rp/current-active-prompt.txt --trials=3 --reuse --greetings-only

# Summarize the checked-in measurements.
node scripts/summarize_codex_rp.mjs
```

`persona-v1.txt` is the first screening prompt. `persona-v2.txt` preserves the language/vision revision used for the original comparisons. The current `persona.txt` adds a more expressive kawaii voice, agentic memory maintenance, and optional audio listening. Comparison and validation metadata include the exact prompt or its SHA-256. The earlier latency tables describe the recorded earlier prompts, not the expanded current tool-enabled companion.

The early mood cases are synthetic descriptions, with normalized fatigue values. `native-mood-cases.json` separately checks the actual kernel scale: fatigue against `f_max` (normally 100), valence from -1 to 1, and energy/arousal from 0 to 1. Supply those units or normalize explicitly when integrating a state snapshot.

## Native desktop, microphone, and vision preview

Start the companion with `./scripts/hyprchan`. It runs independently of the terminal and reopens an existing window without restarting the conversation. You can link that script as `~/.local/bin/hyprchan` for the short `hyprchan` command. Optional settings in `~/.config/hyprchan/preview-launch.json` are a JSON object of `HYPRCHAN_*` environment names and string values; explicit shell settings take precedence. The launcher discovers `~/.local/bin/codex` automatically. Close the chat window to stop her. The direct Python commands below are available for foreground debugging and control.

```sh
# Run in the checked-out project, using system Python for GTK.
python scripts/desktop_codex_rp.py

# Optional: open with the microphone disabled.
python scripts/desktop_codex_rp.py --muted

# Optional: open without camera or screen capture.
python scripts/desktop_codex_rp.py --no-vision

# Optional: keep visual context for chat, with automatic reactions off.
python scripts/desktop_codex_rp.py --no-reactions

# Optional: disable saved facts or playback awareness independently.
python scripts/desktop_codex_rp.py --no-memory --no-audio-awareness

# Optional: keep replies as text without spoken playback.
python scripts/desktop_codex_rp.py --no-voice

# Inspect timing/health without reading conversation text, or close the preview.
python scripts/desktop_codex_rp.py --control '{"type":"status"}'
python scripts/desktop_codex_rp.py --control '{"type":"quit"}'
```

The preview reuses Hyprchan's native GTK sprite renderer, animation assets, OpenCV perception module, and multimodal snapshot source. It adds streamed chat, microphone selection and mute, local spoken replies, automatic visual context, optional reactions, saved user facts, playback listening, and current mood selection. Its character prompt calls for playful gestures, opinions, and natural Russian/English expression. Desktop-tool execution, durable chat history, and the full kernel's memory/state evolution are not started. Mood choices supply the native FVEA units on every turn. Closing the chat window stops capture, speech playback, and the Codex process; reopening an existing instance presents its windows.

Camera and screen capture start automatically. The visible **Camera + screen** toggle releases the camera and stops screenshots; `--no-vision` starts with capture off. Images accompany chat requests and automatic reaction checks. With memory enabled, periodic observations include the webcam so she can learn tentative facts from either source; with memory off, background checks include only the screen. Audio remains local, but recognized text, captured images, relevant saved facts, and audio metadata leave the machine for inference. Turning capture off prevents new attachments; earlier images remain in the current temporary conversation until it is closed.

The existing snapshot provider supplies JPEGs with source labels and capture timestamps. The preview refreshes while speech starts and before a message if its snapshot is older than two seconds, waiting at most 700 ms for that refresh. It also takes periodic snapshots (60 seconds by default, configurable with `MULTIMODAL_SNAPSHOT_INTERVAL_SEC`, minimum 10). It reports image age and missing camera input. The first webcam snapshot follows the three-second warmup instead of waiting for the next periodic interval. Each source from a given capture is attached only once; a new capture is eligible even when its pixels look similar.

She can also call **`look(source)` on demand**, choosing `screen`, `camera`, or `both`. The tool requests a fresh capture and attaches the requested images to her current model turn with labels and timestamps. It reports missing sources, rejects stale frames, times out after five seconds, and cancels if interrupted or capture is switched off. The model is prompted to use it when asked to look again and to avoid tools for greetings. On the tested Codex version, direct dynamic-tool image outputs failed color probes; the bridge therefore uses the supported `turn/steer` input path with explicit `detail: auto`. `node --test scripts/test_desktop_look.mjs` checks cancellation and freshness; `node scripts/verify_desktop_look.mjs /tmp/hyprchan-look-new.json` verifies actual model vision with synthetic colors and capture off.

**Screen reactions** are on by default. Around once a minute while idle, the same conversation receives a fresh screen image and a conditional prompt: volunteer one short kawaii observation if there is something new worth saying; otherwise return exactly `NO_REPLY`. The model makes this decision, including for similar screens. It is prompted to avoid repeating observations, generic offers, and reacting to its own chat/sprite changes. `NO_REPLY` is hidden, with no empty bubble or invented user message. Reactions are buffered until the final decision finishes, including after tool calls; ordinary replies still stream immediately.

Typing or beginning to speak interrupts an active observation so user dialogue takes priority. Pending observations keep only the latest snapshot, and snapshots older than ten seconds are discarded. Capture refreshes requested for user input do not create extra reaction calls. The **Screen reactions** toggle or `--no-reactions` stops background inference while preserving visual context for chat. `HYPRCHAN_REACTION_INTERVAL_SEC` sets the minimum gap between checks (default 60, minimum 10); periodic capture cadence also limits their frequency. Each check uses model inference even when it returns `NO_REPLY`, so leaving reactions enabled adds usage.

The camera is selected from physical V4L2 devices, excluding virtual cameras by default. Use `HYPRCHAN_CAMERA_INDEX` (or `WEBCAM_DEVICE_INDEX`) to choose a specific device. If another application holds it, capture retries every five seconds while screen context remains available. Snapshot files use a private temporary runtime directory and are removed immediately after encoding; images and conversation text are not written to the benchmark results. Capture uses uncompressed intermediate PNG output from `grim`, then the existing JPEG encoding. This removed 838 ms of intermediate compression in one paired local check. See the [grim manual](https://man.archlinux.org/man/grim.1.en).

English is the initial speech language. English and Russian selections use warmed multilingual Whisper `tiny` with CPU int8 and four threads; automatic language detection uses `base`, which passed the short English greeting that `tiny` misclassified as Chinese. Both models are warmed at startup so changing the selector doesn't restart the model. A streaming Silero detector checks 32 ms frames and ends a phrase after 256 ms below its speech threshold. Short pauses can split a sentence; set `HYPRCHAN_END_SILENCE_MS=400` at launch for more pause tolerance. Select the actual microphone in the window, speak, then pause. The input is continuous until muted or closed. Audio is held in memory and transcribed locally; recognized text is sent to the configured Codex model.

Speech uses an isolated environment, separate from the system GTK runtime. Initial setup, if this environment is absent:

```sh
uv venv --python 3.13 ~/.local/share/hyprchan-codex/venv
uv pip install --python ~/.local/share/hyprchan-codex/venv/bin/python 'faster-whisper==1.2.1' 'opencv-python-headless==4.10.0.84'
```

This preview needs existing GTK4/PyGObject, FFmpeg, PulseAudio/PipeWire (`pw-dump`, `pw-record`, `pw-play`), grim, Node with `node:sqlite` (tested on 26.5.1), and the signed-in Codex CLI (tested on 0.163.0). It does not install or upgrade system packages. Override the speech/vision interpreter with `HYPRCHAN_SPEECH_PYTHON`, language with `HYPRCHAN_STT_LANGUAGE=en|ru|auto`, or recognition model with `HYPRCHAN_STT_MODEL`. Codex model/effort/tier overrides are the same as the terminal demo. No login token is printed or passed as an API key.

### Local spoken replies

The separate worker keeps the audition-selected female voices warm: **Kokoro Bella** (`af_bella`, speed 1.08) for English and **Silero Kseniya** (`v5_5_ru`, native SSML pitch `high`) for Russian. Both run locally on CPU with four threads; ONNX idle spinning is disabled. Completed sentences and bounded clauses enter playback while later text is still arriving. Stage directions such as `*waves*`, Markdown markers, code, and `NO_REPLY` are not spoken. Background reactions wait for their final decision before speaking; pre-tool commentary is excluded. Synthesized audio stays in RAM and is played locally through PipeWire. The first spoken phrase selects the language for that reply; mixed-language speech is not a separate multilingual voice.

**Voice on/off** controls spoken replies independently of the microphone. **Stop speaking**, typing, or detected microphone speech cancels the current utterance and drops pending audio. Turning voice back on does not replay old replies. Headphones are recommended for reliable interruption: the preview does not supply acoustic echo cancellation, so loudspeaker output can reach the microphone. Her own PipeWire speech stream is excluded from audio-awareness events and listening targets.

The expressive backend uses an isolated user environment. The following setup uses the CPU-only PyTorch wheel and downloads models from their upstream locations; it does not change system packages:

```sh
uv venv --python 3.13 ~/.local/share/hyprchan-codex/tts-expressive
uv pip install --python ~/.local/share/hyprchan-codex/tts-expressive/bin/python \
  --index https://download.pytorch.org/whl/cpu 'torch==2.13.0+cpu'
uv pip install --python ~/.local/share/hyprchan-codex/tts-expressive/bin/python \
  'kokoro-onnx==0.6.1' 'onnxruntime==1.31.0'
mkdir -p ~/.local/share/hyprchan-codex/voices
curl --fail --location https://models.silero.ai/models/tts/ru/v5_5_ru.pt \
  -o ~/.local/share/hyprchan-codex/voices/silero-v5_5_ru.pt
curl --fail --location https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1/kokoro-v1.0.onnx \
  -o ~/.local/share/hyprchan-codex/voices/kokoro-v1.0.onnx
curl --fail --location https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1/voices-v1.0.bin \
  -o ~/.local/share/hyprchan-codex/voices/voices-v1.0.bin
python scripts/desktop_codex_rp.py
```

Without an override, `HYPRCHAN_TTS_PYTHON` selects `tts-expressive/bin/python` if it exists, otherwise the GUI's Python. Model paths default to `~/.local/share/hyprchan-codex/voices/`; override the directory with `HYPRCHAN_TTS_VOICE_DIR`, or individual model paths with `HYPRCHAN_TTS_VOICE_EN` and `HYPRCHAN_TTS_VOICE_RU`. Kokoro also needs `voices-v1.0.bin` in the voice directory. `HYPRCHAN_TTS_SPEAKER_EN`, `HYPRCHAN_TTS_EN_SPEED`, `HYPRCHAN_TTS_SPEAKER_RU`, and `HYPRCHAN_TTS_RU_PITCH` override the selected voices/prosody. `HYPRCHAN_TTS_THREADS` accepts 1–8. Missing voices/dependencies leave text chat usable and display a voice error. The worker pins the default output at startup; `HYPRCHAN_TTS_SINK` selects a PipeWire output explicitly. Restart after changing the desired output. `HYPRCHAN_TTS_VOLUME` is a 0–1 stream multiplier, default 0.65; system volume is untouched.

**License restriction:** the selected [Silero Russian model](https://github.com/snakers4/silero-models#licence) is covered by [CC BY-NC-SA 4.0](https://github.com/snakers4/silero-models/blob/master/LICENSE). A commercial product needs an appropriately licensed Russian voice or permission from its author. [Kokoro's weights](https://huggingface.co/hexgrad/Kokoro-82M) use Apache 2.0. Voice weights are downloaded separately and are not included in this repository. Implementation references: [Silero SSML](https://github.com/snakers4/silero-models/wiki/SSML), [kokoro-onnx](https://github.com/thewh1teagle/kokoro-onnx), [ONNX Runtime sessions](https://onnxruntime.ai/docs/api/python/api_summary.html), and [PipeWire playback](https://docs.pipewire.org/page_man_pw-cat_1.html).

`python scripts/test_desktop_speech_output.py` checks phrase streaming, action/Markdown cleanup, silent decisions, language choice, and transcript formatting. Run the following with the voice environment to reproduce synthesis and isolated PipeWire output tests:

```sh
~/.local/share/hyprchan-codex/tts-expressive/bin/python scripts/bench_speech_output.py /tmp/hyprchan-tts-new.json
~/.local/share/hyprchan-codex/tts-expressive/bin/python scripts/verify_speech_output.py /tmp/hyprchan-playback-new.json
```

The output test uses a temporary silent sink to measure actual output onset, playback before the reply ends, cancellation, and rejection of cancelled audio. See the [speech-output results](REPORT.md#local-speech-output-and-visible-transcripts). These timings exclude remote inference and physical headphone latency.

The earlier Piper baseline remains available with `HYPRCHAN_TTS_BACKEND=piper`. It requires an interpreter with `piper-tts` (tested 1.8.0), selected via `HYPRCHAN_TTS_PYTHON`, and `en_US-lessac-medium.onnx` / `ru_RU-irina-medium.onnx` plus adjacent `.onnx.json` files in `~/.local/share/piper/voices/`. The benchmark accepts `--backend piper --threads 1,2,4`. Piper's engine is GPL; voice permissions are separate. The [Irina model card](https://huggingface.co/rhasspy/piper-voices/blob/main/ru/ru_RU/irina/medium/MODEL_CARD) lists its dataset license as unknown; check it and the [Lessac model card](https://huggingface.co/rhasspy/piper-voices/blob/main/en/en_US/lessac/medium/MODEL_CARD) before distribution.

### Personal memory and audio awareness

**Memory on** enables three real model tools: `memory_remember`, `memory_recall`, and `memory_forget`. She is instructed to save useful preferences, interests, routines, and ongoing goals as they emerge. Exact supporting quotes from the current user message establish confirmed facts. Supplied recent screen/camera images can establish tentative observations, which cannot overwrite confirmed facts. The prompt excludes transient chatter, credentials, sensitive appearance-based guesses, and profiling other people. This is model-guided fact selection, not a guarantee that every inference is correct. Ask her to correct or forget a fact when needed.

Facts survive restarts in `$XDG_DATA_HOME/hyprchan-codex/memory.sqlite3` (normally `~/.local/share/hyprchan-codex/memory.sqlite3`), with file mode 0600. `HYPRCHAN_MEMORY_PATH` overrides the path. A bounded set of relevant/recent facts is supplied directly, without embedding requests. The visible toggle disables memory tools and future memory context; it keeps the local file. Ask her to forget while memory is enabled to delete records. Earlier messages in the current temporary conversation may still contain those facts, so the prompt also tells her to stop using forgotten information. This small SQLite store is separate from the full kernel's Postgres/Redis memory.

**Audio awareness on** watches new PipeWire nodes and playback starts and sends their names, application, stream serial, and state to the same character conversation. Existing nodes are treated as the startup baseline. Notifications are coalesced briefly, and her own capture streams are excluded. She may react or return `NO_REPLY`; metadata alone does not mean she heard the audio.

The model can call `listen_in(serial, seconds)` for one available playback stream, from 1 to **20 seconds**. Requests of **more than 10 seconds deliver five transcript chunks**; shorter requests deliver one. The tool returns immediately, then chunks enter the conversation as local speech recognition completes. Every chunk is also displayed immediately in one **Heard · application** bubble with `[1/5]` through `[5/5]` labels and the detected language, including an explicit message when no clear speech is recognized. These transcripts remain visible even when she chooses `NO_REPLY`; they are not spoken aloud. Incomplete fragments normally produce no character reaction, so five chunks need not create five reply bubbles. Capture targets the exact PipeWire playback serial, never a fallback microphone or the whole desktop mix. Only one listening job runs at a time, raw audio stays in RAM, and microphone transcription takes queue priority. Recognition can miss or mishear words, especially across short chunk boundaries; it does not identify melodies or other non-speech sounds. Turning audio awareness off cancels capture and pending audio reactions.

Playback always detects language from the audio, independently of the microphone selector and conversation language. With the default model setting it uses warmed multilingual Whisper `base`; a model-supplied language guess can no longer force English media into Russian. Failed repetitive or low-confidence decodes get one wider-beam retry. If that also fails, the bubble says **Unclear audio — could not transcribe reliably** and no guessed words reach the companion. Health metadata records the language probability, model, retry/rejection reason, and timing without transcript text. This does not guarantee correct language or words for every short clip. `HYPRCHAN_STT_MODEL` still overrides the recognition model for both microphone and playback.

Audio observations use the same interruptible background path as screen checks; user typing/speech has priority. Channel events and each transcript chunk can consume inference even when she chooses silence. Saving facts adds tool round trips, so those turns can take several seconds. A greeting needs no tools.

Each **Heard** transcript chunk also requests a fresh screenshot when visual capture is enabled. The caption appears immediately; model delivery waits at most 700 ms for the paired image. Only the desktop screenshot is attached, with its capture time, so she can connect recognized words with visible context without assuming the visible window is the audio source. If capture is off or unavailable, the transcript proceeds as text. Disabling capture discards pending screenshots. This adds image input to the existing audio-observation turn, without creating a separate screen-reaction turn. Microphone messages already receive the normal automatic visual context.

Control examples: `--control '{"type":"memory","active":false}'`, `--control '{"type":"audio","active":false}'`, `--control '{"type":"reactions","active":false}'`, `--control '{"type":"voice","active":false}'`, and `--control '{"type":"stop_voice"}'`. The microphone mute button controls microphone capture independently of playback awareness and camera capture.

Run the targeted checks with:

```sh
node --test scripts/test_desktop_memory.mjs scripts/test_desktop_turn_queue.mjs scripts/test_desktop_visual_context.mjs
python scripts/test_desktop_audio.py
python scripts/verify_desktop_memory.py /tmp/hyprchan-memory-new.json
# Supply the public faster-whisper JFK fixture downloaded outside the checkout.
python scripts/verify_listen_in.py /tmp/jfk.flac /tmp/hyprchan-listening-new.json
python scripts/verify_desktop_audio.py /tmp/jfk.flac /tmp/hyprchan-audio-model-new.json
```

The audio verifiers use a temporary silent sink and clean it up; they never record the microphone. The memory verifier uses fictional facts in a temporary database. Implementation references: [Codex dynamic tools](https://learn.chatgpt.com/docs/app-server), [Node SQLite](https://nodejs.org/download/release/v26.5.0/docs/api/sqlite.html), [PipeWire monitor](https://docs.pipewire.org/page_man_pw-dump_1.html), [PipeWire stream capture](https://docs.pipewire.org/page_man_pw-cat_1.html), and [PipeWire stream properties](https://docs.pipewire.org/page_man_pipewire-props_7.html).

`verify_listen_in.py` deliberately supplies the obsolete Russian hint with the English public fixture; all nonempty chunks must still detect English. `test_desktop_transcription.py` covers repetitive output, recovery, rejection, silence, and cancellation before a retry. To measure the playback recognition policy on synthetic English/Russian greetings and short public speech chunks, run this with the speech environment and your fixture paths:

```bash
~/.local/share/hyprchan-codex/venv/bin/python scripts/verify_playback_languages.py \
  --english /tmp/english-greeting.wav --russian /tmp/russian-greeting.wav \
  --jfk /tmp/jfk.flac --out /tmp/playback-language.json
```

`node --test scripts/test_desktop_visual_context.mjs scripts/test_desktop_turn_queue.mjs` checks image forwarding, source labels, repeat suppression, capture-off behavior, reaction prompts, and cancellation, including cancellation before the model returns its turn ID. `node scripts/verify_codex_vision.mjs /tmp/hyprchan-vision-new.json` checks actual inference through the GUI bridge with synthetic colored frames, including changing images, Russian responses, greetings, and capture off. The saved run is `results/vision-model-20261017.json`. The tested installed route accepted `detail: low` but failed to interpret color probes; the preview uses `auto`, which passed the same real inference checks. This is a route-specific observation, not a general claim about model vision support.

`node scripts/verify_codex_reactions.mjs before.png after.png /tmp/hyprchan-reactions-new.json` exercises the real bridge with two supplied synthetic screenshots: a new observation, an identical repeat, a changed screen, and interruption by a greeting. Use synthetic images only, since the output includes the generated reactions. The saved `results/screen-reactions-20261017.json` used red/green build-status screens labelled BUILD FAILED / BUILD PASSED and 42 tests failed / passed. It passed all five cases, including hidden `NO_REPLY` for the identical screen and immediate interruption of the background turn. This small sample does not guarantee the model's future decision quality.

`scripts/bench_speech_local.py` measures actual local transcription with supplied recordings. `results/speech-local-20261017.json` records 36 trials: tiny with fixed language took 155–265 ms across English/Russian greetings and a three-second English phrase; automatic base took 493–658 ms. These are small warmed sample tests, excluding phrase-end detection and capture buffering. `results/speech-endpoint-20261017.json` checks speech at normal, 0.15x and 0.025x amplitude plus silence and white noise. They do not establish accuracy for arbitrary accents or room noise.

Test recordings: [English hi](https://en.wiktionary.org/wiki/File:En-us-hi.ogg), [Russian привет](https://en.wiktionary.org/wiki/File:Ru-привет.ogg), and the first three seconds of [faster-whisper's JFK test fixture](https://github.com/SYSTRAN/faster-whisper/blob/master/tests/data/jfk.flac). Audio fixtures remain outside the repository. Implementation references: [faster-whisper](https://github.com/SYSTRAN/faster-whisper), [Silero implementation](https://github.com/SYSTRAN/faster-whisper/blob/master/faster_whisper/vad.py), [GTK main-thread dispatch](https://docs.gtk.org/glib/func.idle_add.html), and [FFmpeg Pulse capture](https://ffmpeg.org/ffmpeg-devices.html#pulse).

## What the clocks mean

- `firstTextMs`: from issuing `turn/start` to the first nonempty assistant text delta; excludes reasoning and status events.
- `lastTextMs`: when the last text delta arrives, so all reply text can be visible in a streaming UI.
- `completedMs`: when Codex confirms the entire turn has finished. A client awaiting the completed result waits this long.
- `setupMs` and `startupMs`: local thread and process initialization, measured separately. A running companion should prepare these before accepting messages.
- Fresh-thread trials are not guaranteed cold provider-cache trials. Cache-hit token counts are recorded per response.
- Warm trials reuse the same live thread. Idle trials wait the stated duration without sending another turn to that thread.

The original text-suite times include local Codex processing and remote inference/network latency, but exclude the existing Hyprchan kernel, memory retrieval, UI rendering, audio transcription, and speech synthesis. Later GUI and speech checks identify their own measurement boundaries. `last_tts.firstWriteMs` and `inputToPlaybackWriteMs` measure the first write to the playback pipe, not audible output; the isolated sink verifier measures actual output samples separately. Three- and five-sample screens establish candidates, not production tail latency. Sample p95 in `results/summary.json` uses nearest-rank quantiles and must not be treated as an SLA.

The harness confirms the configured model, reasoning effort, and service tier. It cannot expose the actual backend service-tier receipt. An `ultrafast` request in the first comparison resolved to `null`; those rows are retained for transparency and marked `tierAccepted=false`. The current script rejects such a mismatch rather than reporting it as an Ultrafast result. Model availability is established only by successful inference, not by a model's appearance in the catalog.

## Existing application bottlenecks

The source inspection found several separate delays that a faster model alone cannot remove:

1. `kernel/kernel.py:on_loop` holds `_on_loop_lock` across inference. An incoming message can wait behind passive cognition. `communicate()` wakes the scheduler but does not interrupt the in-flight model call.
2. `_maybe_compact_context_events()` runs before handling user events and can perform up to eight awaited model calls. This is conditional on accumulated context, not a claim that every greeting makes eight calls.
3. `_run_inference_cycle()` awaits memory retrieval before dialogue. The inspected user configuration has `memory.read_active=true`; retrieval can require an embedding request and database queries.
4. `linguistic_engine.py:_run_inference` sends ordinary chat through `ReActAgentExecutor`, whose limit is 100 iterations. The existing prompt asks for explicit `Thought` narration and encourages tools even for presentation. Additional tool turns are possible, not measured in the isolated text benchmark.
5. The language engine awaits the entire agent result before the normal overlay answer. The TUI also polls responses with a default one-second interval.
6. The cached executor is rebuilt only when tool names change. Its captured system prompt and model wrapper can become stale even though new mood/persona prompts and sampling settings are computed each call. Fix this when integrating the dialogue provider so FVEA changes actually reach inference.

An integration should have a dedicated dialogue path using one persistent provider connection per active conversation, a compact current persona/mood/history snapshot, and immediate text streaming. Greetings and ordinary RP should not wait for passive cognition, compaction, associative retrieval, or a tool-planning loop. Run memory maintenance in background work; route actual desktop actions through the existing controlled tools and report their real outcomes. Keep emotion/state evolution, memory recording, and desktop actions explicit rather than removing them to improve a benchmark.

The current LangChain `ChatOpenAI` path is separate from this Codex adapter. Do not paste a ChatGPT OAuth token into an API-key integration or assume that an account has every API model. For a public multi-user product, validate an appropriate per-user sign-in or metered API deployment separately from this local personal prototype.

## Official references

- [Codex app-server and model discovery](https://learn.chatgpt.com/docs/app-server)
- [Codex service-tier configuration](https://learn.chatgpt.com/docs/config-file/config-reference)
- [Fast/Priority processing](https://developers.openai.com/api/docs/guides/fast-mode)
- [GPT-5.6 Luna reasoning settings](https://developers.openai.com/api/docs/models/gpt-5.6-luna)
- [Latency optimization](https://developers.openai.com/api/docs/guides/latency-optimization)
- [Ultrafast availability and persistent connections](https://developers.openai.com/api/docs/guides/ultrafast-mode)

Priority increases usage/cost. The local Codex catalog advertised increased usage for GPT-5.6 Luna. Backend availability, queueing, and network conditions can still produce slow replies; a hard deadline requires a separately designed deadline policy rather than assuming a premium tier guarantees it.
