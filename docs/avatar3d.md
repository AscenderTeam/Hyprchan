# 3D Hyprchan and executable emotes

Open the desktop companion normally with `hyprchan`. Under her portrait choose
**3D · turquoise hoodie**, **3D · cyan & yellow atelier**, or **Pixel art** to
return to the existing sprites.
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
animation. There are 17 built-in gestures; scripts can combine the named face
channels, body/finger bones, hips translation and spatial hand targets. FVEA mood affects the idle expression and motion.
This is an animated companion, not camera-based facial motion capture. The
bundled asset is a customized **pixiv base**; see its
[source, hash and license](../src/hyprchan/assets/avatar3d/CREDITS.md).

The pixel renderer and its sprite sheets remain intact. Missing 3D dependencies
or a GL initialization failure return the GUI to pixel mode with an error.
Native 3D requires GTK 4, desktop OpenGL 3.3, NumPy, Pillow and PyOpenGL. The
optional Python dependencies are listed in
[requirements-avatar3d.txt](../scripts/requirements-avatar3d.txt); no system
package install or upgrade was needed on the tested Asahi machine.

## Cyan and yellow costume

The second costume keeps the turquoise hair, teal eyes, sparkle and Hyprland
pins. Its front portrait takes the sailor collar, striped bow and detached lace
sleeves from the supplied sailor reference, with the neck charm, piped edges
and button details from the second reference. White fabric remains the main
color; narrow black side inserts carry cyan/yellow lacing. Fine stitching,
linked chain, enamel W brooch and satin ribbon folds are separate shaded meshes.
The sleeve headers sit close to the shoulders, leaving a narrow opening above
their scalloped lace instead of the earlier oversized upper-arm cutouts.
The hoodie is a separate selectable model, and switching through pixel mode
retains the last costume. The model receives the current outfit in its emote
context so it can describe the clothes she is actually wearing.

The standing front view is the design target. The bodice uses a continuous
surface with a shaped neckline and moderate chest projection: cloth bridges
the centre instead of following two exaggerated bulges. The licensed base has
missing skin underneath its original shirt; the new shoulder bridge joins its
actual neck and arm boundaries, preserves bone influences and rounds the
clavicle. Cutting that bridge at a flat height previously produced exposed gaps.
The neck ribbon sits below the jaw and is fitted to the actual skin surface
with 3 mm of clearance. Its interpolated skin influences let it deform with
the neck, head and shoulders instead of cutting into them as a rigid oval.
The white collar has its own larger opening around the back of the neck. Its
outer fold sits lower and follows the measured shoulder surface with a shallow
roll. Surface-transferred neck/shoulder weights keep the rear fold clear when
her arms lower, while the front lapels stay attached to the bodice. The camisole
hem sits beneath those lapels.

Cloth has a restrained rose-lilac shadow ramp, softer cast shadows and a small
warm transition tint. Satin ribbons and enamel use distinct highlights. The
reference study used [Ben Ayers' Genshin shader breakdown](https://bjayers.com/blog/9oOD/blender-npr-recreating-the-genshin-impact-shader),
[NiloCat's shader example](https://github.com/ColinLeung-NiloCat/UnityURPToonLitShaderExample),
[Reallusion's clothing construction guidelines](https://wiki.reallusion.com/Content_Dev:CC_Clothing_Modeling_Guidelines)
and [Konstantin Gdalevich's clothing workflow](https://80.lv/articles/003qxl-004adk-character-cloth-production-tips).
These informed the original geometry and shader changes; no game assets or
third-party shader source are bundled.

This outfit's hair uses posed 3D ellipsoids and sleeve/hand capsules for both
joint bending and residual ribbon clearance. A smooth contact band and matching
normal deformation avoid the shoulder creases caused by the old Z-only depth
projection. The hoodie retains its existing depth-map contact route.

The [GPU collision report](../benchmarks/codex-rp/results/avatar-costume-20261018.json)
checks 19 synthetic poses, including turns, raised hands and jumping. All had
zero measured hair intersections with clothing, neck or hands. Original scalp
attachments are reported separately. The main-loop heartbeat stayed below
725 ms; per-pose median render checks ranged from 11.0 to 22.7 ms at 960×1200.
These checks do not establish that every arbitrary executable pose is free of
clipping, or that both live windows sustain the same frame rate.

Native captures: [front](avatar3d-costume/front.png),
[front wave](avatar3d-costume/wave.png), [peek](avatar3d-costume/peek.png),
[turn](avatar3d-costume/turn.png). The GUI integration check switches both
renderers through all three appearances, verifies persistence and exercises
shared motion. Geometry regressions cover native index buffers, bone weights,
independent sleeves, the open shoulder seam and chest/neckline proportions.
A separate triangle-intersection regression checks the neck ribbon, edging and
charm against the skin in seven rest, turn, nod and raised-arm poses. A separate
eight-pose regression covers the white collar, its piping and stitching; checking
only the neck ribbon had missed the white fabric cutting into the neck.

```sh
python scripts/preview_avatar3d.py --outfit cyan_yellow
python scripts/check_avatar_costumes.py
python scripts/bench_avatar_collision.py --outfit cyan_yellow --output /tmp/hyprchan-costume/result.json
```

## Emote tools and scripts

The model has `emote_create(id, title, description, python_code, play_now, seconds)` and
`emote_play(id, seconds)`. It sees the current library, appearance mode and last
run result. The creation tool syntax-checks the source and saves it before
acknowledging success. A started script is not reported as a verified visual
result. The model chooses a duration of **3–30 seconds** for creation and playback, and
saved metadata retains it for picker replay. `animate()` automatically uses that
selected duration, retiming the whole gesture. Use one call with phase branches
for a sequence; manual frame loops can read `duration()` from the SDK. A separate
watchdog adds two seconds for interpreter startup and completion. Stop interrupts
at any time, including during the three-second minimum. Old metadata defaults to
four seconds until the model supplies another duration.

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
restriction. `frame(expressions, bones, hands)` emits one frame, `animate(seconds,
sample, fps=30)` passes progress from 0 to 1, and `ease(t)` smooths transitions.
The [motion module](../src/hyprchan/core/animations/avatar3d/motion.py) lists
supported channels. Expressions are 0–1 and bone rotations are XYZ degrees in
the rig's canonical bind orientation. Arm rest angles are `[0,0,-72]` on the
left and `[0,0,72]` on the right. Unknown/nonfinite frame values are rejected.

For a hand **in front of her face**, use a spatial target instead of estimating
upper-arm angles. Zero arm angles mean a sideways T-pose. The target controls
the **palm centre**; two-bone inverse kinematics positions the shoulder, elbow and
wrist before evaluating the garment's aim/twist constraints. The bundled rig's
finger bones now support open, relaxed, fist, peace and point shapes.

```python
from math import sin
from hyprchan.core.animations.avatar3d.emote_api import animate, ease, hand_target

def wave(t):
    return {
        'expressions': {'smile': .6},
        'hands': {'right': hand_target(
            [.018 * sin(t * 20), -.025, .14],
            shape='open', roll=16 * sin(t * 32),
            weight=ease(min(t / .2, (1-t) / .2)),
        )},
    }

animate(4, wave)
```

Positions are metres from the animated face centre by default: +X her left
(the viewer's right), +Y up, +Z forward. The palm faces forward and fingers point
up; `roll` rotates the wrist in that plane. `[0,-.025,.14]` is directly in front
of the face, while `[-.10,-.025,.14]` is by her right cheek. `space='body'` uses
the chest pivot; `space='world'` uses model coordinates. Targets follow head/body
turns. Weight blends the reach; `shape='peace'` raises the index/middle fingers
and curls the others. The `wave_front` and `peace` built-ins provide ready poses.

Unreachable targets clamp to the arm's physical reach. Completed script results
include measured `palmFromFace`, `errorMm`, and `reachClamped` when a hand target
was held. This checks the skeleton, not visibility or arbitrary cloth collisions.
A script chosen by a tool is no longer replaced by a generic word-triggered wave
if the final reply arrives after the script finishes. Existing executable sources
are not rewritten automatically; older scripts that guess arm angles should use
the target API when positional accuracy matters.

The [spatial harness run](../benchmarks/codex-rp/results/avatar-spatial-20261017.json)
asked the real model to create a front wave and a peace sign using ordinary
language. Both generated scripts used palm targets, completed 121 frames, and
held the palm at least 12.8 cm in front of the face, within 2.3 cm of its
horizontal centre. Measured target error stayed below 1 mm with no reach
clamping. The rig regression checks also cover both arms, head/torso turns,
finger curls, unreachable goals, fading and late text fallback.
The repaired saved wave and peace sign also passed the spatial assertions in
the running GUI and were visually checked in its own framebuffer captures;
[live check metadata](../benchmarks/codex-rp/results/avatar-spatial-live-20261017.json)
contains no chat or desktop images. Background workspaces can pause ordinary
drawing. Explicit avatar captures now render through the GLArea even when
occluded, and motion timing continues independently of compositor callbacks.
The standalone studio also keeps bounded review rendering active when occluded.

The model can invent gestures, save them and reuse them later. Short greetings
do not need tool calls. A distinctive new gesture in a longer reply is a good
occasion to make a script; creation is not mandatory on every turn.

### Jumping through the VRM rig

Ask her to jump, or choose **Emotes… → Happy jump**. The `jump` built-in also
responds to written English/Russian hopping gestures. She can call
`emote_play` with `{"id":"jump","seconds":3}` or create her own variation:

```python
from hyprchan.core.animations.avatar3d.emote_api import animate, jump

animate(3, lambda t: jump(t, height=.10))
```

`jump()` returns a frame with a crouch, leg bends, upward hips translation and
a soft landing. Height is 0.02–0.16 metres. The movement runs through the actual
VRM skeleton; the skinned hoodie, hair and body follow it. The portrait reserves
headroom during the lift. The selected 3–30 second duration retimes the complete
sequence, and Stop immediately clears the lift.

Custom frames can set `root: [x,y,z]` (also the fourth argument to `frame()`).
This translates the humanoid hips in model metres before skinning, hand IK and
hair contact. X/Z stay within ±0.15 m and Y within -0.10..0.18 m; nonfinite and
out-of-range values are rejected. End at `[0,0,0]`. Face/body hand targets follow
the moving rig, while world targets remain fixed. Bone rotations now include
hips, left/right UpperLeg, LowerLeg, Foot and Toes.

The [real Codex check](../benchmarks/codex-rp/results/avatar-jump-agent-20261017.json)
created and ran a 91-frame jump in 3.046 seconds: the VRM hips crouched 3.5 cm,
rose 10 cm and returned to their starting height. All 51 Python and 39 Node
checks passed. The [GPU check](../benchmarks/codex-rp/results/avatar-jump-render-20261017.json)
found zero outfit/neck/hand intersections in crouch, apex, landing and rest;
these are sampled poses, not a proof for every custom jump. Actual captures:
[crouch](avatar3d-jump/crouch.png), [airborne](avatar3d-jump/airborne.png).

The [live GUI check](../benchmarks/codex-rp/results/avatar-jump-live-20261017.json)
also observed the jump's crouch and lift, return to ground and cleared emote
state, with no errors in either portrait renderer.

### Cord hairpin and larger eyes

The original gold sparkle stays on one side; a small shaded Hyprland mark sits
on the other. Its official blue/turquoise outline is adapted into a rounded
5 mm cord with capped ends and subtle woven highlights. Both pins follow the
head bone. [Source and license](../src/hyprchan/assets/avatar3d/CREDITS.md).

The eye openings are widened by up to 10% and raised by up to 16%, with a smooth
falloff into the surrounding skin. Irises, whites, lashes, highlights and facial
blend shapes receive the same deformation, preserving eyelid closure and the
nose bridge. Actual native renders were reviewed across ten expressions:
[front](avatar3d-hairpin/front.png), [turn](avatar3d-hairpin/turn.png),
[wink](avatar3d-hairpin/wink.png). The pixel renderer remains available.

### Executable examples in the model context

The [cookbook manifest](../src/hyprchan/assets/avatar3d/emote-examples/manifest.json)
indexes 19 complete Python scripts. The bridge reads their actual source into
the thread's initial instructions, together with examples of `emote_create` and
`emote_play` arguments. The model receives the code directly, without a lookup
tool call or repeated copies in each message. The ready event and GUI control
status report the number loaded as `emoteExamples` and `emote_examples`.

The examples cover:

- Front waves with either hand, a front/cheek peace sign, and a two-hand peek.
- Targets that follow a turning head, stay over the chest, or remain fixed in
  model coordinates; forward reaching and pointing sideways.
- All five hand shapes, individual finger bones, and head/torso/shoulder motion.
- Every supported expression channel, cheek puffing, winks, and silent mouth
  acting. Normal speech keeps its existing PCM-driven mouth animation.
- A multistage gesture with anticipation and separate hand movements, and the
  lower-level `frame()` protocol with explicit pacing.
- A VRM jump with hips translation, crouching knees, airborne lift and landing.

Each script can be copied independently and adapted. Face/body/world coordinates
and arm ownership are explained explicitly: a hand target controls its arm and
fingers, while the raw-bone example uses the separate path without a target.
Catalogue names are references, not saved emote IDs; `emote_create` makes a script
available in the persistent picker. Pixel art remains selectable.

Regression checks execute all 19 source files, sample their animation curves,
validate every frame, and evaluate reaches on the actual bundled skeleton.
They check all expression/shape/space categories, both hands, rigid arm lengths,
finite transforms, reach accuracy and smooth release. The
[two-hand peek](avatar3d-examples/peek-two-hands.png) and
[chest-relative gesture](avatar3d-examples/hand-on-chest.png) were also reviewed
in native GL captures.

The [full-context Codex run](../benchmarks/codex-rp/results/avatar-examples-20261017/result.json)
loaded the original 18 examples and generated its own front wave and peace sign. Both
scripts completed 121 frames, with target error below 1 mm and no reach clamping.
Held palms stayed at least 12.8 cm in front of the face. Greeting text completed
in 1.283–1.363 s; script creation plus final text took 3.597 s and 4.342 s.
This small sample does not establish a strict latency guarantee or prove that
the extra examples caused a speed improvement. The run reported zero
reasoning-output tokens despite medium being configured for gesture creation.

## Artist-guided visual checks

The implementation was iterated using actual GL framebuffer captures, front
and side views, and a ten-expression gallery. The review caught sleeve
constraints left in the bind pose, gaps at bent elbows, hair cutting through the
hoodie, excessive face shading, and an accessory sitting too far off the hair.
The final clothing pass replaces the round shoulder pieces with a continuous
garment, narrows the torso and sleeves, adds a fuller bust without widening the
shoulders or waist, and adds
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
- [Two-bone IK](https://docs.unity3d.com/Packages/com.unity.animation.rigging@1.2/manual/constraints/TwoBoneIKConstraint.html):
  target position/orientation and an elbow bend hint; the native solver follows
  this rigging pattern without a Unity dependency.

Run a visual studio without microphone, capture or model requests:

```sh
python scripts/preview_avatar3d.py
python scripts/preview_avatar3d.py --gallery /tmp/hyprchan-expression-review
python scripts/preview_avatar3d.py --emote wave_front
python scripts/preview_avatar3d.py --script /path/to/emote.py --capture /tmp/emote.png
```

The gallery renders ten expressions into PNGs and an HTML contact sheet.
The live two-portrait check measured 24.0–24.6 fps with no GL errors, confirmed
that pixel mode stops 3D rendering, and replayed a saved 121-frame emote after
restart. The visible Stop control cancelled a run; capture and voice preferences
were preserved. See [live verification metadata](../benchmarks/codex-rp/results/avatar-live-20261017.json).
The renderer is tailored to the bundled rig; it is not a general VRM importer
or a complete implementation of MToon or VRM spring physics. The supported
MToon lighting/outline subset is implemented natively in GLSL; this is not a Unity
lilToon runtime. Hair has damped secondary motion, length-preserving joint
contact around the chest, hood, sleeves and hands, and a small GPU clearance pass
against the actual posed torso. Extreme user-authored poses can still intersect
clothing or leave the bust framing; the checks below cover a finite set of poses.

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

The later spatial-tool run completed its two greetings in 2.140 s and 1.499 s;
one missed the two-second target. Creating the wave and peace scripts plus the
final response took 4.523 s and 4.022 s, respectively, with animation playback
starting during the tool call. These turns also reported zero reasoning tokens.

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
python scripts/bench_avatar_agent.py --spatial --output /tmp/hyprchan-avatar-spatial.json
```

The last command uses the real authenticated Codex route and executes the
synthetic animation it generates. It uses no personal memories, images, audio,
web search or notifications.

## Printed emblem lighting and selectable timing (2026-10-17)

The gold-orange background and rounded teal W now inherit the actual hoodie surface, interpolated normals and skin weights. They receive the same MToon light ramp and cast shadows as the fabric. The print does not have a separate outline hull or cast a floating shadow. Front and hand-over-chest GL captures were reviewed.

The model chose a four-second gesture in an authenticated local Codex test and its script completed 121 frames in 4.025 seconds without timeout. A separate subprocess regression retimed a 20-second script to the selected 3.2 seconds and verified its final frame; invalid sub-three-second, over-limit and nonfinite choices are rejected. All 45 Python and 39 Node checks passed. Evidence: [avatar-duration-20261017.json](../benchmarks/codex-rp/results/avatar-duration-20261017.json).

## Hair contact and responsive verification (2026-10-17)

Long hair now bends through its authored joint chains instead of receiving a
fixed oval chest offset. Contact volumes follow the posed chest, hood, arms,
palms, fingers and thumbs. Root attachments and segment lengths stay fixed.
Each segment restores towards its authored direction so an elbow contact does
not turn the entire lower strand into a straight horizontal extension.

A front/back depth pass of the actual posed torso clears residual ribbon
thickness. One-time mesh subdivision prevents coarse triangles cutting across
the curved garment. The visible surface, outlines, cast shadows and normals use
the same deformation. This is tailored to the bundled model, not a complete
VRMC SpringBone implementation.

The [collision report](../benchmarks/codex-rp/results/avatar-hair-20261017.json)
checks actual GPU positions and triangle intersections in 15 views/poses,
including turns, nods, a lean, looking up, one-hand waves and two-hand peeks at
half and full reach. All had zero measured intersections with the hoodie,
neck or hands. Authored scalp/face attachment overlaps remain separately
reported. The reference disables contact on the same refined mesh; it is a
geometry diagnostic, not a performance comparison with the previous release.

The benchmark checks copied arrays in a worker thread and yields between GL
frames. Its GUI heartbeat stayed responsive (448 ms maximum gap); closing the
window cancels the check. An earlier blocking version triggered compositor
unresponsive-app dialogs; those test dialogs were closed and the repeat run
completed without new ones. Captures contain only the bundled avatar:
[front](avatar3d-hair/rest.png), [turn](avatar3d-hair/left.png),
[half-raised hand](avatar3d-hair/wave_mid.png), [peek](avatar3d-hair/peek.png).

All 47 Python checks pass, including rigid hair lengths and refinement that
preserves surface area, winding, UVs and normalized skin weights. The deployed
source files match the tested checkout, and an actual overlay capture was
reviewed without GL errors. The live microphone remained on with Russian
selected and voice output stayed off. [Live metadata](../benchmarks/codex-rp/results/avatar-hair-live-20261017.json)
records frame cadence as well: about 7 fps for both portraits in the initial
desktop state, then 23.4 fps for the chat portrait during a focus attempt while
the other portrait paused. Visibility affects compositor scheduling; these
samples do not establish sustained 24 fps for both with the new hair pass.

```sh
python scripts/bench_avatar_collision.py --output /tmp/hyprchan-hair/result.json
```
