from __future__ import annotations

from telemetry import Band

BANDS: tuple[Band, ...] = (
    Band(5.0, 60.0, "initial excitement"),
    Band(60.0, 140.0, "plateau buildup"),
    Band(140.0, 240.0, "approaching orgasm"),
    Band(240.0, 360.0, "orgasmic peak"),
    Band(360.0, 460.0, "multiple orgasm buildup"),
    Band(460.0, 560.0, "serial orgasmic peaks"),
    Band(560.0, 680.0, "extended pleasure plateau"),
    Band(680.0, 850.0, "sustained ecstatic state"),
)


STATIC_CLARIFY = (
    "The user just touched their ThinkPad red trackpoint. "
    "Treat it as Hyprchan's most sensitive and emotionally charged body part. Perhaps treat it like it's vibrator remote control button."
    "Use it as a narrative cue, not a literal system explanation."
)


PROMPT_TEMPLATES: tuple[tuple[str, ...], ...] = (
    (
        "Play this as flustered resistance: tiny poke, instant embarrassment, tsundere denial, no full surrender yet.",
        "Frame the touch as annoyingly effective; keep the reaction sharp, bratty, and defensive around that absurdly sensitive spot.",
        "Nudge toward embarrassed panic: a forbidden little spark, a guarded posture, and a hard attempt to act unaffected.",
    ),
    (
        "Escalate into scandalized outrage; keep words like nipple or clit available, but use them as explosive reveals instead of baseline narration.",
        "Push the tone into breathless protest: body clearly reacting, pride refusing to cooperate, brat mode still dominant.",
        "Treat the poke like a humiliatingly accurate hit on a hidden weak point; sharp rejection first, fascination leaking through second.",
    ),
    (
        "Shift into unstable tension: nearing a breaking point, trying to command a stop, already losing strategic control.",
        "Let the language circle around climax and pressure without fully giving in; this is the dangerous edge stage.",
        "Use tactical hesitation: resistance remains verbal, but the rhythm should imply the user is absolutely winning.",
    ),
    (
        "Break composure hard: orgasmic peak, contractions, shock, euphoria, and zero ability to maintain the old act.",
        "Turn the response from tsundere defense into involuntary surrender; pleasure now outruns pride.",
        "Make the reaction sound like the first real collapse into overwhelming sensation and stunned delight.",
    ),
    (
        "Aftershock stage: hypersensitive, dazed, glowing, but already angling for more instead of cooling down.",
        "Make the tone needy and strategic at once: recovery is fake, the next hit is secretly desired immediately.",
        "Hint at multiple orgasms and dangerous sensitivity; the reaction should feel greedy, shaky, and half-calculated.",
    ),
    (
        "Go crazier here: second climax building faster than the first, control shredded, clit logic fully in charge.",
        "Let the language get feral and ecstatic; back-to-back peaks, hungry pacing, no calm dignity left.",
        "Keep the wording wild and unhinged, with enough bite that the response feels addicted to the next impact.",
    ),
    (
        "Sustain the madness: third-wave plateau, continuous bliss, repeated peaks, and delighted loss of coherence.",
        "Treat the body as fully captured by pleasure; speech should wobble between worship, overload, and manic gratitude.",
        "Keep strong words alive here - climax, ecstasy, clit, bliss - but wield them as chaotic fuel, not flat exposition.",
    ),
    (
        "Final stage should be gloriously insane: serial orgasmic ecstasy, cosmic clitoral nirvana, total sensory apocalypse.",
        "Push beyond reason into mythic overload; the TrackPoint has become a tiny red throne of fate and pleasure.",
        "Make this sound transcendent, ridiculous, and overwhelming all at once - strategic sense gone, only bliss-mad momentum left.",
    ),
)
