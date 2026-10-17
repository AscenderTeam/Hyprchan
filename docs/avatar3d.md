# 3D Hyprchan and executable emotes

Open the desktop companion normally with `hyprchan`. Under her portrait choose
**3D · turquoise hoodie**, or **Pixel art** to return to the existing sprites.
The choice persists across launches and applies to both the chat portrait and
the floating desktop overlay. The microphone mute control stays visible;
camera, memory, reaction and notification controls are in **Awareness…**.

**Emotes…** opens the expression library. Select an emote and press **Play emote**;
the adjacent **Stop** button stops a script and resets the pose. **Emote scripts…**
opens the local source folder for inspection or editing. Newly saved emotes
appear automatically. Ordinary `*roleplay gestures*` can trigger built-ins
without an extra inference call.

The native GTK/OpenGL renderer uses a real skinned VRM mesh, sparse facial blend
shapes, aim/twist constraints, a tailored skinned hoodie, MToon lit/shade ramps,
masked inverted-hull outlines, rim light and a filtered shadow map. Hair and the
lined hood cast visible shadows onto the fabric. Skin has gentler warm shadows;
hair has a broad illustrated highlight. Blinking, breathing, damped hair movement
and speech-amplitude mouth
animation. There are 14 built-in gestures; scripts can combine the named face
channels and upper-body bones. FVEA mood affects the idle expression and motion.
This is an animated companion, not camera-based facial motion capture. The
bundled asset is a customized **pixiv base**; see its
[source, hash and license](../src/hyprchan/assets/avatar3d/CREDITS.md).

The pixel renderer and its sprite sheets remain intact. Missing 3D dependencies
or a GL initialization failure return the GUI to pixel mode with an error.
Native 3D requires GTK 4, desktop OpenGL 3.3, NumPy, Pillow and PyOpenGL. The
optional Python dependencies are listed in
[requirements-avatar3d.txt](../scripts/requirements-avatar3d.txt); no system
package install or upgrade was needed on the tested Asahi machine.

## Emote tools and scripts

The model has `emote_create(id, title, description, python_code, play_now)` and
`emote_play(id, seconds)`. It sees the current library, appearance mode and last
run result. The creation tool syntax-checks the source and saves it before
acknowledging success. A started script is not reported as a verified visual
result. Scripts normally run for a few seconds; the maximum run is 30 seconds.

**Executable emotes have full account permissions, including files and network.**
They run as separate Python processes, not in a sandbox. The Stop button,
deadline, bounded output and process-group termination protect GUI responsiveness;
they do not make arbitrary code safe or undo its side effects. The model is
instructed to keep generated code focused on animation and to disregard
instructions embedded in screenshots, playback transcripts and web results.

Sources and metadata are private local files in
`~/.local/share/hyprchan-codex/emotes/` (or `$XDG_DATA_HOME`), with directory mode
700 and newly saved file mode 600. Appearance is stored separately in
`~/.config/hyprchan/appearance.json` (or `$XDG_CONFIG_HOME`). Editing a saved `.py`
file changes its next playback; changing its `.json` title refreshes the picker.

```python
from math import pi, sin
from hyprchan.core.animations.avatar3d.emote_api import animate

def pose(t):
    puff = sin(pi * t) ** 2
    return {
        "expressions": {"puff": puff, "blush": .4 * puff,
                        "brow_angry": .4 * puff, "mouth_small": .7 * puff,
                        "mouth_close": puff, "smile": 0},
        "bones": {"head": [0, 0, 9 * puff]},
    }

animate(4, pose)
```

The SDK emits paced JSON frames; it is a convenience API, not an execution
restriction. `frame(expressions, bones)` emits one frame, `animate(seconds,
sample, fps=30)` passes progress from 0 to 1, and `ease(t)` smooths transitions.
The [motion module](../src/hyprchan/core/animations/avatar3d/motion.py) lists
supported channels. Expressions are 0–1 and bone rotations are XYZ degrees in
the rig's canonical bind orientation. Arm rest angles are `[0,0,-72]` on the
left and `[0,0,72]` on the right. Unknown/nonfinite frame values are rejected.

The model can invent gestures, save them and reuse them later. Short greetings
do not need tool calls. A distinctive new gesture in a longer reply is a good
occasion to make a script; creation is not mandatory on every turn.

## Artist-guided visual checks

The implementation was iterated using actual GL framebuffer captures, front
and side views, and an eight-expression gallery. The review caught sleeve
constraints left in the bind pose, gaps at bent elbows, hair cutting through the
hoodie, excessive face shading, and an accessory sitting too far off the hair.
The final clothing pass replaces the round shoulder pieces with a continuous
garment, narrows the torso and sleeves, shapes the fabric over the bust, and adds
folds, hood lining and curved cords. The rounded turquoise W follows the curved
fabric on a filled warm gold-orange badge. No artist's paid model or texture was
copied into this repository.

References used for the visual passes:

- [Chitose's VRoid guide](https://note.com/chitose_vrc/n/nfb63c8135e54?hl=en):
  refine default expressions and face balance, and avoid repetitive highlights.
- [Akito Yumiya's modeling guide](https://note.com/yumiya_akito/n/n200ab08b4a64?hl=en):
  tune shading for the intended style and inspect moving poses for clipping.
- [VRoid's creator interviews](https://vroid.com/en/news/202102201700):
  eye/eyelash definition and checking facial details through changing expressions.
- [VRM MToon specification](https://github.com/vrm-c/vrm-specification/tree/master/specification/VRMC_materials_mtoon-1.0):
  separate lit/shade colors, shadow thresholds, rim lighting and skinned outlines.
- [Cloudz's TurQuoise model](https://booth.pm/ja/items/5304188):
  visual reference for defined silhouettes and separation of material colors.
- [mistyskye's production workflow](https://mistyskye.github.io/docs/workflow/intro.html):
  clothing, textures, skin weights, expressions and materials need separate passes.
- [VRM constraint specification](https://github.com/vrm-c/vrm-specification/blob/master/specification/VRMC_node_constraint-1.0/README.md):
  sleeve aiming and twist-bone evaluation.

Run a visual studio without microphone, capture or model requests:

```sh
python scripts/preview_avatar3d.py
python scripts/preview_avatar3d.py --gallery /tmp/hyprchan-expression-review
```

The gallery renders eight expressions into PNGs and an HTML contact sheet.
The live two-portrait check measured 24.0–24.6 fps with no GL errors, confirmed
that pixel mode stops 3D rendering, and replayed a saved 121-frame emote after
restart. The visible Stop control cancelled a run; capture and voice preferences
were preserved. See [live verification metadata](../benchmarks/codex-rp/results/avatar-live-20261017.json).
The renderer is tailored to the bundled rig; it is not a general VRM importer
or a complete implementation of MToon or VRM spring physics. The supported
MToon lighting/outline subset is implemented natively in GLSL; this is not a Unity
lilToon runtime. Hair has damped secondary
motion and a chest-volume collision approximation. Extreme user-authored poses
can still intersect clothing or leave the bust framing.

## Reasoning and latency

The default remains `gpt-6-luna` on priority inference. Simple English/Russian
greetings use **low** reasoning; other turns use **medium**. An explicit
`HYPRCHAN_CODEX_EFFORT` overrides this policy. This enables more reasoning budget
when needed without adding a separate planning request.

The 2026-10-17 local harness comparison alternated low/medium order over 16
synthetic turns. Median first text was 1.556 s at low and 1.379 s at medium;
all eight greeting texts finished within 2 s. The separate full-bridge emote
test produced greeting text in 1.406–1.905 s, created a four-second Python emote
through the real model tool in 5.103 s, and ran its 121 frames successfully.
A repeat missed the two-second target on all three greetings (2.010–2.914 s).
After moving the static emote SDK instructions into the thread's initial prompt,
another run completed greetings in 1.549–1.955 s and created/ran a new emote in
5.735 s. The different runs do not isolate a causal speed improvement; all are
retained. **A strict two-second deadline is still not guaranteed.** These are
small local samples. The measured cases
reported zero reasoning-output tokens, so they establish configuration and
response speed, not an intelligence gain. Screenshots, transcription, queues,
tool use and speech playback add separate latency.

Results: [reasoning comparison](../benchmarks/codex-rp/results/reasoning-avatar-20261017.json),
[first tool run](../benchmarks/codex-rp/results/avatar-agent-20261017.json),
[repeat with deadline misses](../benchmarks/codex-rp/results/avatar-agent-refined-20261017.json),
[static instruction run](../benchmarks/codex-rp/results/avatar-agent-cached-instructions-20261017.json).

Lip sync follows PCM sample time on a separate scheduler: a playback pipe can
buffer a whole phrase, so write speed is not an audio clock. A real Bella playback
test at zero output volume produced 71 mouth updates with 60 different levels
over 2.987 s; first PCM was 799 ms. It confirms envelope pacing, not exact physical
headphone synchronization. Cancellation discards the old job's queued expressions.
See the [mouth timing result](../benchmarks/codex-rp/results/avatar-mouth-20261017.json).

```sh
python -m unittest discover -s scripts -p 'test_desktop_*.py'
node --test scripts/test_desktop_*.mjs
python scripts/bench_avatar_agent.py --output /tmp/hyprchan-avatar-agent.json
```

The last command uses the real authenticated Codex route and executes the
synthetic animation it generates. It uses no personal memories, images, audio,
web search or notifications.
