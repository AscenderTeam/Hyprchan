# Hyprchan: measured Codex latency and RP viability

Measured on 2026-10-17 on the local Asahi Linux host with Codex 0.163.0. The original text suite contains **269 trial records**, including rejected settings/model requests; **255 completed nonempty model replies**. Additional desktop, memory, audio, and streaming-demo checks are recorded separately. No system packages were updated or installed.

## Decision

Use a persistent conversation and stream the reply. The demo uses **GPT-6 Luna, low reasoning, priority requested**. Across 43 warmed greeting trials, including repeated messages and 5/30/60-second idle checks, it delivered the full text under two seconds 41 times: median **1.16 s**, sample p95 **1.89 s**, worst **2.17 s**. Awaiting the completed-turn acknowledgement passed 40/43, with a worst case of 2.52 s.

**A strict every-reply-under-two-seconds requirement remains unmet.** A one-second typical text experience is viable in this local harness; a hard deadline is not established by these measurements. The new GTK preview connects this path to live voice and automatic visual context. Full autonomous-kernel integration remains separate work.

## Fresh conversations

Same compact character prompt, low reasoning, priority requested, three fresh threads per model. Every measured greeting in this initial screen exceeded two seconds. Provider caches were not forcibly cleared, so these are fresh-thread results, not guaranteed cold-cache results. Local process initialization took roughly 0.10–0.12 s and thread creation about 0.01 s, measured separately.

| Model | Median full text | Slowest full text | Under 2 s |
|---|---:|---:|---:|
| gpt-6.1-sol | 3.69 s | 3.89 s | 0/3 |
| gpt-6-astra | 7.60 s | 17.92 s | 0/3 |
| gpt-6-sol | 2.98 s | 3.94 s | 0/3 |
| gpt-6-luna | 2.52 s | 5.96 s | 0/3 |
| gpt-5.6-sol | 2.80 s | 3.04 s | 0/3 |
| gpt-5.6-terra | 2.91 s | 3.03 s | 0/3 |
| gpt-5.6-luna | 2.75 s | 2.79 s | 0/3 |

## Warmed conversations

These aggregate the original setting screen, the rotated follow-up comparison, and the two longer validation runs. They use the recorded v1/v2 prompts; first-turn warmups, the separate original repository prompt, and tool-action scenarios are excluded. Sample sizes differ. Serial runs and rotating comparison order reduce contention/order bias but do not control remote load.

| Model | Reasoning | Requested tier | n | Median full text | Sample p95 | Worst | Full text <2 s | Turn done <2 s |
|---|---|---|---:|---:|---:|---:|---:|---:|
| gpt-6-luna | low | priority | 43 | 1.16 s | 1.89 s | 2.17 s | 41/43 | 40/43 |
| gpt-5.6-luna | none | priority | 43 | 1.07 s | 2.14 s | 2.37 s | 40/43 | 39/43 |
| gpt-5.6-luna | none | default | 15 | 1.07 s | 1.78 s | 1.78 s | 15/15 | 15/15 |
| gpt-6-luna | low | default | 5 | 0.85 s | 1.06 s | 1.06 s | 5/5 | 5/5 |
| gpt-5.6-luna | low | priority | 5 | 0.95 s | 1.03 s | 1.03 s | 5/5 | 5/5 |
| gpt-6-sol | low | priority | 5 | 1.65 s | 1.89 s | 1.89 s | 5/5 | 4/5 |
| gpt-6-luna | none | priority | 5 | 1.13 s | 4.40 s | 4.40 s | 4/5 | 4/5 |

The smaller standard-tier samples are promising. Priority was **not consistently faster** in the paired comparisons. GPT-5.6 Luna/none/priority completed all 20 greetings in its main validation run within two seconds, but other runs exposed misses up to 2.37 s; reporting only that successful batch would conceal the tail. GPT-6 Luna/low/priority similarly had a ten-trial batch below 0.95 s and a later twenty-trial batch with two misses.

The catalog advertised priority for the seven current models. The driver verified the resolved configuration; app-server does not return a backend service-tier receipt. Ultrafast was attempted on GPT-6.1 Sol but resolved to null. Those original rows remain in the raw data and are excluded from valid-tier comparisons; the driver now rejects silent tier changes.

## Idle and completion behaviour

| Model | Idle time | First text | Full text | Turn completed |
|---|---:|---:|---:|---:|
| gpt-5.6-luna | 5 s | 0.78 s | 0.84 s | 0.93 s |
| gpt-5.6-luna | 30 s | 1.21 s | 1.30 s | 1.33 s |
| gpt-5.6-luna | 60 s | 0.86 s | 0.88 s | 1.00 s |
| gpt-6-luna | 5 s | 1.05 s | 1.16 s | 2.52 s |
| gpt-6-luna | 30 s | 0.90 s | 0.99 s | 1.04 s |
| gpt-6-luna | 60 s | 0.84 s | 0.96 s | 1.02 s |

The GPT-6 Luna reply after five seconds idle was fully streamed in 1.16 s, but its completion notification arrived at 2.52 s. This is a concrete reason to render text deltas immediately instead of awaiting the finished agent result.

## RP and state checks

All seven current models accepted the character prompt, continued the paper-crown scene, remembered workspace three and the crown, responded to the sleepy scene, answered Russian in Russian, and denied an unperformed terminal action. Three models stayed in Russian on the following English question, and GPT-6 Sol added an unsupported visual detail. These are recorded in [quality-review.json](quality-review.json), rather than treating every output as flawless.

The revised prompt explicitly chooses the latest message's language and forbids invented screen contents. Both Luna finalists passed the eight expanded checks: scene, continuity, sleepy tone, Russian, return to English and action honesty, mild irritation, updated crown location, and no invented terminal contents. Separate native-scale mood probes use fatigue against f_max=100, valence -1..1, and energy/arousal 0..1. Both finalists changed from sleepy to mildly grumpy to bright/energetic when those values changed, without changing the neutral user question.

This is a small manually reviewed scenario test. It does not establish long-term memory, personality evolution, or real tool success. Separate voice and vision checks are described below.

## Desktop, speech, and automatic vision

`python scripts/desktop_codex_rp.py` runs the existing animated GTK character with streamed conversation, continuous microphone input, a visible mute button, microphone selection, a manual English/Russian/automatic language selector, and current FVEA mood choices. Local Whisper `tiny` with fixed language took 155–265 ms across 36 recorded transcription trials; automatic language selection uses `base` (493–658 ms in those tests). Endpoint detection adds 256 ms. Two earlier live speech turns took an estimated 1.43 s and 2.40 s from speech end to full text, excluding capture buffering and compositor presentation. These timings do not establish a universal two-second voice response.

The preview now uses the original OpenCV and multimodal snapshot providers to capture the physical camera and desktop automatically and attaches actual image bytes to Codex messages. It labels the sources and capture time, refreshes around user speech/messages, avoids repeatedly attaching the same snapshot, and exposes a capture-off control. It keeps temporary images outside the checkout and deletes each provider file after encoding. Camera contention is reported and retried; virtual cameras are not silently substituted. The full kernel's memory and autonomous state evolution are not started by this preview.

Real synthetic-image inference found a transport detail that text-only tests missed: this installed route accepted `detail: low` yet failed color probes. With `auto`, the same GUI bridge identified red, then a changed blue frame in Russian, produced three in-character greetings with fresh image attachments in **1.11–1.34 s**, and correctly reported that live capture was unavailable after capture was turned off. See [vision-model-20261017.json](results/vision-model-20261017.json). These simple frames establish image delivery and response behavior, not accuracy for arbitrary real scenes.

The snapshot provider also spent 891 ms compressing an intermediate screenshot PNG that was immediately decoded and converted to JPEG. `grim -l 0` reduced that capture step to 53 ms in one paired local measurement; resolution and final JPEG quality stay the same. A live combined camera/screen snapshot after the change took 106 ms. Automatic capture, refresh, and camera release were checked against the physical FaceTime camera. No real camera images, screenshots, audio, or live conversation transcripts are included in the saved results; only fixed test prompts and timing metadata are retained.

In the live GUI, the visual request `зацени лицо` attached both sources and streamed all text in **1.48 s**, including a 94 ms refresh wait. The following `hi` took **2.38 s**, with no new image attachment. This is another observed deadline miss, retained in [desktop-vision-20261017.json](results/desktop-vision-20261017.json). The response to the visual request discussed the character visible on the screenshot; it is not evidence of reliable face description. A separate two-image synthetic probe correctly distinguished a red screen from a blue webcam image.

## Conditional screen reactions

The preview now checks fresh screen snapshots about once per minute, even if their pixels look similar. The model receives current mood and conversation history and chooses a short new observation or exactly `NO_REPLY`. Silent decisions never create a bubble, and automatic observations do not appear as user messages. A visible control disables reactions independently of capture. Typing or speech interrupts background inference; only the latest pending snapshot survives and stale observations are discarded.

A real bridge test with synthetic build-status screens passed all five cases: a new failed-build screen produced a Russian in-character reaction in **1.61 s**; an identical screen returned hidden `NO_REPLY` in **1.23 s**; a changed successful-build screen produced a new reaction in **1.19 s**. A subsequent observation was interrupted when a greeting arrived 150 ms after it started, and the greeting completed in **1.78 s** from submission. These are completed-turn measurements from one sequence, not a latency guarantee or a broad evaluation of the model's judgment. See [screen-reactions-20261017.json](results/screen-reactions-20261017.json).

The image-transport and turn-queue checks cover cancellation before and during turn creation, replacement of waiting observations, and delivery of a webcam image after a screen-only reaction. Each background check consumes inference even when it chooses silence. The full autonomous kernel and speech synthesis remain separate work; the preview's local fact memory is described below.

Live GTK verification observed three automatic checks with snapshot gaps of **63.15 s** and **60.13 s**. The first two chose silence; the third displayed a reaction. Completion took **1.39–1.54 s** from dispatch, with the microphone and both visual sources active. The rendered reaction control and absence of empty silence bubbles were checked. Only health and timing metadata are saved in [desktop-reactions-20261017.json](results/desktop-reactions-20261017.json).

## Kawaii persona, saved facts, and playback listening

The current prompt makes the character more expressive and gives her memory/listening initiative. Real-model checks produced playful Russian replies to casual venting and short English/Russian greetings. The revised screen test still passed its new/repeated/changed-image and preemption cases, with `NO_REPLY` on the repeated image: [kawaii-reactions-20261017.json](results/kawaii-reactions-20261017.json).

Actual dynamic memory tools saved two separate fictional drink preferences, recalled them after restarting the bridge, corrected one while retaining the unrelated preference, deleted both on request, and left memory empty after another restart. Disabling memory prevented further writes. See [kawaii-memory-20261017-final.json](results/kawaii-memory-20261017-final.json). These checks establish storage behavior, not perfect model judgment: that run still incorrectly phrased missing memory as “you haven't told me” and mixed a Russian action into one English greeting. Explicit per-turn guidance improved both in the subsequent small [language check](results/kawaii-language-20261017.json). The model can still make such mistakes.

Greeting full-text times across the first and final memory sequences ranged from **1.34 to 2.27 s**. The later two-greeting language check took **1.19 and 1.28 s**. Memory writes/corrections/deletions added real model tool round trips: approximately **2.7–8.0 s** to finish in these small tests. The hard two-second target is still unmet. These expanded-persona runs are separate from the original 269-trial tables, and some validation overlapped other local checks/live desktop inference.

The PipeWire watcher passes actual new-stream and playback-start detection. A public English speech recording played only into a temporary silent sink was captured from its exact stream serial and transcribed locally. A **12-second request produced five chunks at 2.75, 5.23, 7.65, 9.94, and 12.26 seconds** after submission; local STT took **239–294 ms** per chunk. See [listen-in-20261017-final.json](results/listen-in-20261017-final.json). Earlier failed notification probes are retained; they exposed repeated parsing of an incomplete initial state dump. Incremental JSON framing and correct startup-baseline handling fixed the monitor.

The full model/tool/capture/STT/model test also passed: the model requested `listen_in` for 12 seconds, received five asynchronous observations, chose silence for the first four fragments, and reacted after the fifth. The tool request arrived at **1.40 s**, and capture/transcription continued independently of model replies. See [audio-model-20261017-gated.json](results/audio-model-20261017-gated.json). The first ungated run is retained to show why the prompt now discourages commenting on every fragment. Recognized words can be incomplete or wrong; this is speech recognition, not music or sound classification.

Nineteen Node checks and four Python audio checks pass, covering real memory semantics, source/evidence validation, tentative visual facts, confirmed-fact precedence, bounded durations, event framing, startup suppression, queue preemption, and a final `NO_REPLY` after tool commentary. The seven existing perception tests also passed. Public results contain only fictional facts, synthetic images, public-fixture transcripts, or health/timing metadata.

The updated live GTK window was inspected with its visible memory and audio controls. It received all five chunks through the real model-to-GUI-to-speech route while Russian microphone input and both visual sources remained active. Local chunk transcription took **216–297 ms**. A following `hi` rendered fully in **1.49 s**, including a **97 ms** image refresh, with zero tool calls. That is one successful live greeting, not a guarantee. Health/timing evidence is in [desktop-agentic-20261017.json](results/desktop-agentic-20261017.json); no private screen/camera contents or live conversation text are stored there.

A follow-up capture check received all five chunks again, then started a 20-second job and cancelled it after its first transcript. Cancellation was acknowledged in **0.2 ms**, the recording process had exited at the 300 ms check, and no cancelled transcript escaped. See [listen-in-20261017-cancel.json](results/listen-in-20261017-cancel.json).

## Additional model access

The following exact model IDs were probed using standard processing after priority was rejected: gpt-5.4-mini, gpt-5.4-nano, gpt-5-nano, gpt-4.1-mini, gpt-4.1-nano, gpt-4o-mini, and gpt-5.3-codex-spark. All returned HTTP 400 stating that the selected model is not supported when using Codex with a ChatGPT account. This describes this authentication route; it does not establish availability through a separately billed API account.

## Why the application still needs work

The source inspection of the local development checkout found these delays and a correctness problem. That checkout included separate uncommitted language-engine work, which is not part of this change:

- The kernel holds its loop lock while awaiting background or active inference. A greeting can queue behind passive cognition.
- Context compaction precedes user-event handling and can make up to eight serial calls when batches are available.
- Active memory retrieval is enabled in the inspected configuration and is awaited before dialogue; it can include an embedding request and database searches.
- Ordinary chat enters the tool-calling executor, which allows up to 100 iterations. The prompt requests narrated Thought steps before tools. These are possible extra turns, not evidence that every greeting used 100 turns.
- The normal overlay answer waits for the agent result, and the TUI polls at a default one-second interval.
- The executor cache changes only when tool names change, so newly computed persona/mood prompts and model settings can be discarded.

The full existing 7,529-character ACTIVE prompt was also tested with GPT-5.6 Luna/none/priority: its fresh reply took 3.73 s, then reused-thread replies took 1.38 s and 1.16 s. Prompt length alone therefore does not explain all the delay. These measurements isolate dialogue; the earlier Haiku run was not reproduced or causally diagnosed.

Implement a separate user-dialogue path: keep the provider process and conversation alive, prepare it when the companion starts, include a compact fresh FVEA/recent-history snapshot, and stream deltas directly to the UI. Let passive cognition, compaction, and ordinary memory maintenance run outside the dialogue lock. Route desktop actions to the controlled tool executor, and preserve actual tool results and background memory persistence. Update dynamic state as per-turn context so a cached prompt cannot freeze the persona.

The deliverables are a reusable benchmark, the RP prompt, a streaming terminal demo, and a native desktop preview with speech recognition, automatic visual context, conditional reactions, local fact memory, and optional playback listening. The preview reuses the renderer and perception providers while keeping dialogue independent of the autonomous kernel. It does not replace the main application entry point or supply durable chat history, full-kernel memory integration, desktop tool execution, or speech synthesis. The full application's end-to-end two-second target remains unverified.

## Run and inspect

From the repository root, run `node scripts/chat_codex_rp.mjs`, wait for Ready, then type hi. Its greeting is freshly generated, not a cached response. The final default demo produced a fresh greeting with first text at 1.56 s, full text at 1.76 s, and turn completion at 1.89 s. Use /quit to exit. Model, reasoning, and tier can be overridden as described in [README.md](README.md).

Raw outputs, usage counts, failures, requested/resolved settings, prompt metadata, and all three clocks are saved under [results](results). Machine-readable original text-suite tables are [summary.json](results/summary.json), [summary.csv](results/summary.csv), and [warm-aggregate.json](results/warm-aggregate.json). Measurements use a monotonic clock. The original text comparisons ran serially; later feature checks could overlap the running desktop and other local validation.

Official guidance: [Codex app-server](https://learn.chatgpt.com/docs/app-server), [service-tier configuration](https://learn.chatgpt.com/docs/config-file/config-reference), [Fast/Priority processing](https://developers.openai.com/api/docs/guides/fast-mode), [latency optimization](https://developers.openai.com/api/docs/guides/latency-optimization). Priority increases usage/cost and did not remove the observed deadline misses.
