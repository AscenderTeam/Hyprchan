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

`persona-v1.txt` is the first screening prompt. `persona.txt` adds explicit switching back to the latest message's language and prohibits inventing unseen screen contents. Comparison and validation metadata include the exact prompt; the initial screen records its SHA-256, matching `persona-v1.txt`.

The early mood cases are synthetic descriptions, with normalized fatigue values. `native-mood-cases.json` separately checks the actual kernel scale: fatigue against `f_max` (normally 100), valence from -1 to 1, and energy/arousal from 0 to 1. Supply those units or normalize explicitly when integrating a state snapshot.

## Native desktop, microphone, and vision preview

```sh
# Run in the checked-out project, using system Python for GTK.
python scripts/desktop_codex_rp.py

# Optional: open with the microphone disabled.
python scripts/desktop_codex_rp.py --muted

# Optional: open without camera or screen capture.
python scripts/desktop_codex_rp.py --no-vision

# Inspect timing/health without reading conversation text, or close the preview.
python scripts/desktop_codex_rp.py --control '{"type":"status"}'
python scripts/desktop_codex_rp.py --control '{"type":"quit"}'
```

The preview reuses Hyprchan's native GTK sprite renderer, animation assets, OpenCV perception module, and multimodal snapshot source. It adds a chat window, immediate reply streaming, microphone selection and level meter, a visible mute control, automatic visual context, and current mood selection. It is a separate local preview, not the full autonomous kernel: there is no desktop-tool execution, background memory maintenance, durable chat history, or speech synthesis. Mood choices supply the native FVEA units on every turn. Closing the chat window stops capture and the Codex process; reopening an existing instance presents its windows.

Camera and screen capture start automatically. The visible **Camera + screen** toggle releases the camera and stops screenshots; `--no-vision` starts with capture off. Images accompany chat requests to Codex. Audio remains local, but recognized text and the captured images leave the machine for inference. Turning capture off prevents new attachments; earlier images remain in the current temporary conversation until it is closed.

The existing snapshot provider supplies JPEGs with source labels and capture timestamps. The preview refreshes while speech starts and before a message if its snapshot is older than two seconds, waiting at most 700 ms for that refresh. It also takes periodic snapshots (120 seconds by default, configurable with `MULTIMODAL_SNAPSHOT_INTERVAL_SEC`, minimum 10). It reports image age and missing camera input. The first webcam snapshot follows the three-second warmup instead of waiting for the next periodic interval. Unchanged snapshots are not attached again. No background model calls run on capture events.

The camera is selected from physical V4L2 devices, excluding virtual cameras by default. Use `HYPRCHAN_CAMERA_INDEX` (or `WEBCAM_DEVICE_INDEX`) to choose a specific device. If another application holds it, capture retries every five seconds while screen context remains available. Snapshot files use a private temporary runtime directory and are removed immediately after encoding; images and conversation text are not written to the benchmark results. Capture uses uncompressed intermediate PNG output from `grim`, then the existing JPEG encoding. This removed 838 ms of intermediate compression in one paired local check. See the [grim manual](https://man.archlinux.org/man/grim.1.en).

English is the initial speech language. English and Russian selections use warmed multilingual Whisper `tiny` with CPU int8 and four threads; automatic language detection uses `base`, which passed the short English greeting that `tiny` misclassified as Chinese. Both models are warmed at startup so changing the selector doesn't restart the model. A streaming Silero detector checks 32 ms frames and ends a phrase after 256 ms below its speech threshold. Short pauses can split a sentence; set `HYPRCHAN_END_SILENCE_MS=400` at launch for more pause tolerance. Select the actual microphone in the window, speak, then pause. The input is continuous until muted or closed. Audio is held in memory and transcribed locally; recognized text is sent to the configured Codex model.

Speech uses an isolated environment, separate from the system GTK runtime. Initial setup, if this environment is absent:

```sh
uv venv --python 3.13 ~/.local/share/hyprchan-codex/venv
uv pip install --python ~/.local/share/hyprchan-codex/venv/bin/python 'faster-whisper==1.2.1' 'opencv-python-headless==4.10.0.84'
```

This preview needs existing GTK4/PyGObject, FFmpeg, PulseAudio/PipeWire, grim, Node, and the signed-in Codex CLI. It does not install or upgrade system packages. Override the speech/vision interpreter with `HYPRCHAN_SPEECH_PYTHON`, language with `HYPRCHAN_STT_LANGUAGE=en|ru|auto`, or recognition model with `HYPRCHAN_STT_MODEL`. Codex model/effort/tier overrides are the same as the terminal demo. No login token is printed or passed as an API key.

`node --test scripts/test_desktop_visual_context.mjs` checks image forwarding, source labels, repeat suppression, and capture-off behavior. `node scripts/verify_codex_vision.mjs /tmp/hyprchan-vision-new.json` checks actual inference through the GUI bridge with synthetic colored frames, including changing images, Russian responses, greetings, and capture off. The saved run is `results/vision-model-20261017.json`. The tested installed route accepted `detail: low` but failed to interpret color probes; the preview uses `auto`, which passed the same real inference checks. This is a route-specific observation, not a general claim about model vision support.

`scripts/bench_speech_local.py` measures actual local transcription with supplied recordings. `results/speech-local-20261017.json` records 36 trials: tiny with fixed language took 155–265 ms across English/Russian greetings and a three-second English phrase; automatic base took 493–658 ms. These are small warmed sample tests, excluding phrase-end detection and capture buffering. `results/speech-endpoint-20261017.json` checks speech at normal, 0.15x and 0.025x amplitude plus silence and white noise. They do not establish accuracy for arbitrary accents or room noise.

Test recordings: [English hi](https://en.wiktionary.org/wiki/File:En-us-hi.ogg), [Russian привет](https://en.wiktionary.org/wiki/File:Ru-привет.ogg), and the first three seconds of [faster-whisper's JFK test fixture](https://github.com/SYSTRAN/faster-whisper/blob/master/tests/data/jfk.flac). Audio fixtures remain outside the repository. Implementation references: [faster-whisper](https://github.com/SYSTRAN/faster-whisper), [Silero implementation](https://github.com/SYSTRAN/faster-whisper/blob/master/faster_whisper/vad.py), [GTK main-thread dispatch](https://docs.gtk.org/glib/func.idle_add.html), and [FFmpeg Pulse capture](https://ffmpeg.org/ffmpeg-devices.html#pulse).

## What the clocks mean

- `firstTextMs`: from issuing `turn/start` to the first nonempty assistant text delta; excludes reasoning and status events.
- `lastTextMs`: when the last text delta arrives, so all reply text can be visible in a streaming UI.
- `completedMs`: when Codex confirms the entire turn has finished. A client awaiting the completed result waits this long.
- `setupMs` and `startupMs`: local thread and process initialization, measured separately. A running companion should prepare these before accepting messages.
- Fresh-thread trials are not guaranteed cold provider-cache trials. Cache-hit token counts are recorded per response.
- Warm trials reuse the same live thread. Idle trials wait the stated duration without sending another turn to that thread.

All times include local Codex processing and remote inference/network latency, but exclude the existing Hyprchan kernel, memory retrieval, UI rendering, audio transcription, and speech synthesis. Three- and five-sample screens establish candidates, not production tail latency. Sample p95 in `results/summary.json` uses nearest-rank quantiles and must not be treated as an SLA.

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
