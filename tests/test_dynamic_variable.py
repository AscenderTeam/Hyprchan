from core.hypraios.utils.dynamic_variable import DynamicVariable


def test_dynamic_variable_clamps_on_write_by_default() -> None:
    variable = DynamicVariable(value=0.2, min_val=0.0, max_val=1.0)

    variable.value = 3.0
    assert variable.value == 1.0

    variable.value = -2.0
    assert variable.value == 0.0


def test_dynamic_variable_can_skip_clamp_on_write() -> None:
    variable = DynamicVariable(
        value=0.2,
        min_val=0.0,
        max_val=1.0,
        clamp_on_write=False,
    )

    variable.value = 3.0
    assert variable.value == 3.0

    variable.clamp()
    assert variable.value == 1.0


def test_dynamic_variable_step_applies_decay_factor() -> None:
    variable = DynamicVariable(value=10.0, min_val=0.0, max_val=20.0, decay=0.8)

    variable.step()

    assert variable.value == 8.0
