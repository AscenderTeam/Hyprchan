from core.hypraios.utils.fault_adaptive_parameter import FaultAdaptiveParameter


def test_adjust_positive_error_moves_value_down_and_persists(tmp_path) -> None:
    parameter = FaultAdaptiveParameter(
        value=1.0,
        min_delta=0.5,
        max_delta=0.5,
        step=0.1,
        cache_key="test_param",
        weights_dir=str(tmp_path),
    )

    adjusted = parameter.adjust(2.0)

    assert adjusted == 0.8
    cache_file = tmp_path / "test_param.json"
    assert cache_file.exists()


def test_adjust_respects_bounds_near_limits(tmp_path) -> None:
    parameter = FaultAdaptiveParameter(
        value=1.0,
        min_delta=0.5,
        max_delta=0.5,
        step=0.1,
        cache_key="bounded_param",
        weights_dir=str(tmp_path),
    )
    parameter.value = 0.52

    adjusted = parameter.adjust(5.0)

    assert adjusted == 0.6


def test_init_loads_cached_value_when_present(tmp_path) -> None:
    cache_file = tmp_path / "cached_param.json"
    cache_file.write_text('{"value": 1.3}', encoding="utf-8")

    parameter = FaultAdaptiveParameter(
        value=1.0,
        min_delta=0.5,
        max_delta=0.5,
        step=0.1,
        cache_key="cached_param",
        weights_dir=str(tmp_path),
    )

    assert parameter.value == 1.3
