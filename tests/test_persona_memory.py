from core.hypraios.linguistic.persona_memory import PersonaMemory


def test_primary_persona_prompt_contains_first_startup_memory():
    memory = PersonaMemory()
    prompt = memory.build_primary_persona_prompt("ACTIVE")

    assert "PRIMARY NARRATIVE DIRECTIVE" in prompt
    assert "first_startup" in prompt
    assert "Hyprland" in prompt
    assert "Roleplay is allowed" in prompt


def test_persona_traits_change_with_memory_content():
    memory = PersonaMemory()
    baseline = memory.trait_snapshot()

    memory.remember_turn(
        "lets rp and make it playful hehe",
        "*smiles brightly* Yay, lets roleplay in a neon city!",
    )
    updated = memory.trait_snapshot()

    assert updated != baseline
