from enum import Enum


FAULT_ROUTING = {

    # Kernel loop timing
    "cooldown_thrash": {
        "layer": "kernel",
        "params": ["gamma", "rho", "cooldown_floor"],
        "direction": {
            "gamma": "increase",
            "rho": "increase",
            "cooldown_floor": "increase",
        },
    },

    "attention_ignored": {
        "layer": "kernel",
        "params": ["gamma", "rho"],
        "direction": {
            "gamma": "decrease",
            "rho": "decrease",
        },
    },

    # Phase activation
    "self_activation_overuse": {
        "layer": "phase",
        "params": ["k_self"],
        "direction": {
            "k_self": "increase",
        },
    },

    "self_activation_missed": {
        "layer": "phase",
        "params": ["k_self"],
        "direction": {
            "k_self": "decrease",
        },
    },

    # Fatigue accumulation
    "fatigue_saturation": {
        "layer": "fatigue",
        "params": ["k_tok", "k_evt", "k_inf"],
        "direction": {
            "k_tok": "decrease",
            "k_evt": "decrease",
            "k_inf": "decrease",
        },
    },

    "fatigue_never_builds": {
        "layer": "fatigue",
        "params": ["k_tok", "k_evt", "k_inf"],
        "direction": {
            "k_tok": "increase",
            "k_evt": "increase",
            "k_inf": "increase",
        },
    },

    # Sleep ↔ memory coupling
    "sleep_overextension": {
        "layer": "sleep",
        "params": ["k_sleep"],
        "direction": {
            "k_sleep": "increase",
        },
    },

    "sleep_underrecovery": {
        "layer": "sleep",
        "params": ["k_sleep"],
        "direction": {
            "k_sleep": "decrease",
        },
    },

    # Rudeness smoothing
    "rudeness_spike_sensitive": {
        "layer": "mood_filter",
        "params": ["lambda_r"],
        "direction": {
            "lambda_r": "increase",
        },
    },

    "rudeness_never_accumulates": {
        "layer": "mood_filter",
        "params": ["lambda_r"],
        "direction": {
            "lambda_r": "decrease",
        },
    },

    # Valence dynamics
    "valence_stuck_negative": {
        "layer": "valence",
        "params": ["k_v", "alpha_p"],
        "direction": {
            "k_v": "increase",
            "alpha_p": "increase",
        },
    },

    "valence_oscillation": {
        "layer": "valence",
        "params": ["k_v", "alpha_p", "alpha_r"],
        "direction": {
            "k_v": "decrease",
            "alpha_p": "decrease",
            "alpha_r": "decrease",
        },
    },

    "forced_cheerfulness": {
        "layer": "valence",
        "params": ["k_v"],
        "direction": {
            "k_v": "decrease",
        },
    },

    # Energy dynamics
    "energy_collapse": {
        "layer": "energy",
        "params": ["beta_f"],
        "direction": {
            "beta_f": "decrease",
        },
    },

    "energy_hyperactivity": {
        "layer": "energy",
        "params": ["beta_a"],
        "direction": {
            "beta_a": "decrease",
        },
    },

    # Observer boundary
    "observer_dominance": {
        "layer": "observer",
        "params": ["lambda_obs"],
        "direction": {
            "lambda_obs": "decrease",
        },
    },

    "observer_irrelevant": {
        "layer": "observer",
        "params": ["lambda_obs"],
        "direction": {
            "lambda_obs": "increase",
        },
    },

    # Logit bias
    "style_overcoercion": {
        "layer": "output",
        "params": ["bias_gain"],
        "direction": {
            "bias_gain": "decrease",
        },
    },

    "style_invisible": {
        "layer": "output",
        "params": ["bias_gain"],
        "direction": {
            "bias_gain": "increase",
        },
    },
}


class Phases(Enum):
    PASSIVE = 0,
    ACTIVE = 1,
    MAINT = 3,
    SLEEP = 4