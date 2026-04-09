from controllers.v1.events.vision.vision_service import VisionService


def test_build_candidate_indices_prioritizes_preferred_index() -> None:
    indices = VisionService._build_candidate_indices(preferred=3, max_index=4)

    assert indices[0] == 3
    assert indices == [3, 0, 1, 2, 4]


def test_build_candidate_indices_handles_negative_values() -> None:
    indices = VisionService._build_candidate_indices(preferred=-2, max_index=-1)

    assert indices == [0]
