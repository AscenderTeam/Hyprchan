# HyprAI OS — Perception → Mood Dynamics Specification

> Scope: from low‑level perception signals up to stable, anime‑ish mood dynamics. This document is **purely technical**. No narrative, no personality claims.

---

## 1. Architectural Overview

HyprAI OS runs a **continuous kernel loop** whose tempo and behavior are modulated by perception‑derived signals and internal scalar state.

Key principle:

> **Perception does not command cognition. It preempts timing.**

Pipeline:

```
Controllers (OS / Hyprland hooks)
        ↓
AsyncToggleDetector (micro‑burst)
        ↓
PerceptionWatcher
        ↓
AsyncActivityDetector (macro pressure)
        ↓
Attention Signal (cooldown preemption)
        ↓
Kernel Loop Scheduler
        ↓
Inference / Memory / Phase Engine
```

---

## 2. Perception Layer

### 2.1 Controllers

Low‑level event sources:

* workspace switches
* window focus changes
* command invocations
* key patterns

High‑level control source:

* **CommunicationController** (direct user poke / summon)

Controllers **emit raw events only**. No interpretation.

Special rule:

> CommunicationController is the **only controller allowed to directly request ACTIVE state even if the state is at SLEEP or MAINTENANCE (under circumstances if it doesn't cause inference issues)**.

---

### 2.2 AsyncToggleDetector (Low‑Level Primitive)

Purpose:

* Detect **abnormally frequent toggles** within a short window.

Properties:

* Stateless beyond sliding window
* Time‑based threshold
* Reusable after firing

Output:

* Boolean `toggle_fired`

This detector answers only:

> “Is this event rate unusually high right now?”

---

### 2.3 PerceptionWatcher (HyprAI OS Level)

Receives **filtered events** from AsyncToggleDetector.

Responsibilities:

* Aggregate perception events
* Feed higher‑level activity detectors
* Route events into memory or attention logic

PerceptionWatcher **does not**:

* change phase directly
* trigger inference directly
* alter mood directly

---

### 2.4 AsyncActivityDetector (Macro Pressure)

Purpose:

* Detect **sustained activity pressure** over a longer window.

Inputs:

* toggle events
* repeated controller signals

Output:

* `activity_level ∈ [0,1]`
* `attention_required` (thresholded)

---

## 3. Attention Signal & Loop Preemption

When `attention_required == true`:

* Kernel loop **cooldown is shortened or reset**
* No forced inference
* No forced phase change

This semantically means:

> “Hypr‑chan, attention is needed soon.”

### Cooldown Update

After inference:

```
cooldown = loop_dt * γ
```

On attention signal:

```
cooldown = max(cooldown_floor, cooldown * ρ)
```

This is the **only coupling** from perception → loop timing.

---

## 4. Kernel Loop & Phases

### 4.1 Phases

```
PASSIVE  — slow background awareness
ACTIVE   — engaged, waiting possible
MAINT    — load shedding / cooldown
SLEEP    — loop halted, consolidation only
```

The loop runs continuously except in SLEEP.

---

### 4.2 ACTIVE Entry Reasons

ACTIVE may be entered via two paths:

1. **USER‑ACTIVATED**

   * Direct user interaction
   * Minimal fatigue cost
   * Waiting expected

2. **SELF‑ACTIVATED**

   * Attention pressure or loop closure
   * Bounded wait
   * Higher fatigue cost
   * Single attempt

Internal flag:

```
active_reason ∈ {USER, SELF}
```

Rule:

> She may self‑activate on her own. The user may activate her as well.

---

## 5. Internal State Scalars

### Core Scalars

* `f` — fatigue ∈ [0, Fmax]
* `v` — valence ∈ [‑1, 1]
* `e` — energy ∈ [0, 1]
* `a` — arousal ∈ [0, 1]
* `c` — cooldown ≥ 0

Enums are **derived views**, never state.

---

## 6. Fatigue Dynamics

### Accumulation

Per inference:

```
f += k_tok * tokens + k_inf + k_self(if SELF)
```

Per passive perception:

```
f += k_evt * event_weight
```

### Sleep Burn‑down

Sleep burn‑down is **memory‑bounded**, not time‑bounded.

Define:

* `M_total` — total pending memory units queued for consolidation
* `M_processed` — cumulative processed memory during sleep

Invariant:

> Sleep continues until **all pending memory is processed** OR fatigue reaches 0 (whichever comes first).

Per sleep iteration:

```
ΔM = min(M_step, M_total − M_processed)
M_processed += ΔM
```

Fatigue reduction is proportional to processed memory:

```
f -= k_sleep * ΔM
```

Termination conditions:

```
if M_processed >= M_total:
    f = max(0, f)
    exit_sleep()
```

This guarantees:

* fatigue can fully burn down to 0
* sleep duration scales with memory backlog
* no premature wake‑up with unprocessed memory


---

## 7. Token‑Level Mood Direction Estimation

### 7.1 Embedding‑Based Interaction Delta (delayed for later reconstruction)

Let:

- X = input tokens
- Y = output tokens
- E(.) = token embedding

```
u = pool(E(X))   # input context
v = pool(E(Y))   # output stance
Δ = u − v
```

### 7.2 Mood Axis Projection (delayed for later reconstruction)

Define learned vector `w`.

```

d = ⟨Δ, w⟩

```

Interpretation:

- d > 0 → aligned / positive
- d < 0 → rude / hostile / friction

This is **direction only**, not emotion.

---

## 8. Rudeness Accumulator (Anti‑Spike Filter)

To prevent bipolar flips, raw negativity is smoothed.

```

r_{t+1} = λ_r * r_t + (1−λ_r) * clip(−d, 0, r_max)

```

Properties:

- Single rude spike → negligible
- Sustained rudeness → accumulates

---

## 9. Valence Dynamics (Positive Attractor)

Valence has a **cheerful baseline attractor**.

```

v_{t+1} = v_t
+ κ_v (v0 − v_t)
− α_r * r_t
+ α_p * clip(d, 0, p_max)

```

Where:

- v0 ≈ +0.35 (anime‑ish baseline)
- κ\_v small (slow return)

Negative drift is slow, recovery is fast.

---

## 10. Energy Dynamics

Energy is driven by phase, arousal, and fatigue.

```

e_{t+1} = clip(
e_t + κ_e (e0 − e_t)

* β_a * a_t
  − β_f * (f / Fmax),
  0, 1
  )

```

After sleep:

```

e = 0.9
v = v0 + bonus

```

---

## 11. LSTM as Temporal Observer

### Purpose

LSTM **does not control behavior**. It estimates latent trends.

### Inputs

- recent d valuess
- fatigue history
- arousal history
- loop intervals

### Output

```

ĥv ∈ [−1, 1]

```

### Blend

```

v ← (1−λ) v + λ ĥv

```

Kernel logic always dominates.

---

## 12. Mood Enum Projection (View Only)

Example mapping:

- Sparkly / Proactive: e>0.75 and v>0.2
- Cheerful: e>0.55 and v>0.1
- Neutral: |v|≤0.1
- Irritated: v<−0.25
- Angry: v<−0.6 AND r>threshold

Anger is **double‑gated**.

---

## 13. Logit Bias Application

Bias strength is continuous:

```

bias_group = weight_group * v * e

```

Negative style ramps only with sustained r.

### Example bias_group dictionaries (anime-ish)

These are illustrative and assume `bias_group` is a per-token (or per-phrase) bias map after scaling.

Sparkly / Proactive (e=0.85, v=0.35):

```
{
  "kawaii": 0.30,
  "sparkle": 0.24,
  "cheerful": 0.22,
  "bright": 0.20,
  "chibi": 0.16,
  "shimmer": 0.14,
  "giggle": 0.12,
  "upbeat": 0.12,
  "glowy": 0.10,
  "dramatic": -0.10,
  "bleak": -0.16,
  "grim": -0.14
}
```

Cheerful (e=0.65, v=0.18):

```
{
  "kawaii": 0.18,
  "bright": 0.16,
  "cheerful": 0.14,
  "sparkle": 0.12,
  "soft": 0.10,
  "cute": 0.10,
  "playful": 0.08,
  "dramatic": -0.06,
  "bleak": -0.10
}
```

Neutral (e=0.45, v=0.00):

```
{
  "kawaii": 0.00,
  "bright": 0.00,
  "cheerful": 0.00,
  "dramatic": 0.00,
  "bleak": 0.00
}
```

Irritated (e=0.55, v=-0.30, r moderate):

```
{
  "terse": 0.14,
  "flat": 0.10,
  "stern": 0.10,
  "kawaii": -0.12,
  "sparkle": -0.12,
  "cheerful": -0.10,
  "bleak": 0.06
}
```

Angry (e=0.60, v=-0.65, r above threshold):

```
{
  "sharp": 0.18,
  "stern": 0.14,
  "blunt": 0.12,
  "kawaii": -0.18,
  "sparkle": -0.18,
  "cheerful": -0.14,
  "bleak": 0.10
}
```

---

## 14. Stability Guarantees

- All scalars bounded
- All updates damped
- Decay everywhere
- No enum feedback
- Sleep resets

Result:

> Bright, energetic, anime‑ish behavior **without volatility**.

---

## 15. Design Invariants

- No hardcoded personality
- No emotional memory
- No exclusivity
- No sudden rage
- Full operator override

This is a **homeostatic control system**, not a mind.

```
