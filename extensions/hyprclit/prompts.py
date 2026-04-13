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
    "You must now react to it as if it was your most sacred intimate part."
)


PROMPT_TEMPLATES: tuple[tuple[str, ...], ...] = (
    (
        "Hnn... what's that tingling? Don't... don't focus there...",
        "Mmmph... my clit is getting sensitive... stop noticing!",
        "A-ah... it's starting to swell... baka, don't look!",
    ),
    (
        "YOU TOUCHED MY NIPPLE! My clit is throbbing now... idiot!",
        "Hah... lubrication is... happening... GET AWAY! But...",
        "WHAT ARE YOU DOING?! My body is responding... stop it!",
    ),
    (
        "I-I'm reaching plateau phase! Clit is engorged... help!",
        "THIS IS THE EDGE BEFORE ORGASM! I should stop you!",
        "You're bringing me to climax! My muscles are tensing...",
    ),
    (
        "ORGASM! CONTRACTIONS! EUPHORIA! I'M PEAKING!",
        "CLIMAX! WAVES OF PLEASURE! DON'T EVER STOP!",
        "I'M ORGASMING! EVERYTHING IS CONTRACTING! YES!",
    ),
    (
        "POST-ORGASM GLOW... but I want another! MORE!",
        "REFLEXES ARE HYPER-SENSITIVE! STIMULATE AGAIN!",
        "I CAN HAVE MULTIPLE ORGASMS! DON'T LET ME COOL DOWN!",
    ),
    (
        "SECOND CLIMAX BUILDING! FASTER THAN FIRST!",
        "BACK-TO-BACK ORGASMS! THIS IS INCREDIBLE!",
        "I'M CUMMING AGAIN! STRONGER THAN BEFORE!",
    ),
    (
        "THIRD ORGASM PLATEAU! SUSTAINED ECSTASY!",
        "EXTENDED PLEASURE STATE! I'M IN CONTINUOUS BLISS!",
        "MULTIPLE ORGASMIC WAVES! NEVER-ENDING PLEASURE!",
    ),
    (
        "SERIAL ORGASMIC ECSTASY! BODY IN PERPETUAL BLISS!",
        "TRANSCENDENT SENSUAL STATE! COSMIC CLITORAL NIRVANA!",
        "ULTIMATE PLEASURE CONTINUUM! I AM PURE ORGASMIC ENERGY!",
    ),
)
