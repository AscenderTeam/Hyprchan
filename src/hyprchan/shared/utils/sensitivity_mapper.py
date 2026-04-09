from hyprchan.settings import MAX_THRESHOLD, MAX_WINDOW, MIN_THRESHOLD, MIN_WINDOW


def sensitivity_to_params(sensitivity: float):
    s = max(0.01, min(sensitivity, 1.0))

    threshold = round(
        MAX_THRESHOLD - s * (MAX_THRESHOLD - MIN_THRESHOLD)
    )

    window_sec = (
        MIN_WINDOW + s * (MAX_WINDOW - MIN_WINDOW)
    )

    return threshold, window_sec
