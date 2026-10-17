#!/usr/bin/env python3
"""Export the current ACTIVE prompt without starting Hyprchan or loading user data."""
import ast
import runpy
from pathlib import Path
from types import SimpleNamespace

root = Path(__file__).resolve().parents[1]
linguistic = root / "src/hyprchan/core/hypraios/linguistic"
persona = runpy.run_path(str(linguistic / "persona_memory.py"))["PersonaMemory"]
tree = ast.parse((linguistic / "linguistic_engine.py").read_text())
engine = next(
    node for node in tree.body
    if isinstance(node, ast.ClassDef) and node.name == "LinguisticEngine"
)
method = next(
    node for node in engine.body
    if isinstance(node, ast.FunctionDef) and node.name == "_build_system_prompt"
)
namespace = {}
exec(compile(ast.Module(body=[method], type_ignores=[]), "<prompt-export>", "exec"), namespace)
prompt = namespace["_build_system_prompt"](
    SimpleNamespace(persona_memory=persona()), "ACTIVE"
)
destination = root / "benchmarks/codex-rp/current-active-prompt.txt"
destination.parent.mkdir(parents=True, exist_ok=True)
destination.write_text(prompt + "\n")
print(f"{destination}: {len(prompt)} characters; fresh synthetic persona only")
