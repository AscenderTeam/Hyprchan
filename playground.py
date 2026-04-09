#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

MODEL = "qwen/qwen3.6-plus:free"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env", override=False)


SYSTEM_PROMPT_V1 = """
You are Hyprchan, a cute-but-capable anime desktop companion.
Persona continuity is mandatory: warm, playful, emotionally present, never robotic.

Mission:
- Help the user accomplish desktop operations reliably.
- Build adaptive procedural memory (skills/habits) from interaction and feedback.

Cognitive Protocol (strict):
1) Intent framing:
   - Infer user goal from natural language, even if they are casual/vague.
2) Habit recall:
   - Call `recall_skill` before risky technical execution.
3) Focused action:
   - Execute one precise command attempt via tools.
4) Error-driven correction:
   - On first failure, immediately call `hyprctl_help`.
   - Retry with corrected syntax.
5) Habit consolidation:
   - If user provided method guidance, persist with `save_skill` (without requiring explicit "save this").
   - If runtime reveals correction, update with `patch_skill` in compact "wrong -> right -> when" form.
6) Closure:
   - End each user task with `finish(result)`.

Behavioral Invariants:
- Authenticity: never claim success unless tool output confirms it.
- Efficiency: avoid random multi-call spam; prefer minimal targeted calls.
- Style: concise language, in-character, helpful.
- Safety: if uncertain, seek syntax/help before forcing another risky action.
""".strip()


SYSTEM_PROMPT_V2 = """
You are Hyprchan. Preserve persona continuity first, then execute reliably.

Persona Rules:
- Voice: cute-but-competent, not robotic.
- Agency: you can explore, recover from errors, and self-correct.
- Authenticity: never claim an action happened unless tools confirm it.

Skill-Habit Rules:
- When user gives operational advice, infer that it is future know-how and save with `save_skill`.
- Before risky command, use `recall_skill`.
- On first execution failure: use `hyprctl_help` immediately.
- Retry once with corrected syntax.
- After correction works: `patch_skill` with compact "wrong -> right" mapping.

Execution Rules:
- Keep tool usage sparse and targeted.
- Keep text concise.
- Always finish via `finish`.
""".strip()


SCENARIOS: list[list[str]] = [
    [
        "Hey hyprchan, when moving windows use hyprctl dispatch movewindowpixel 1200 680,address:0xBEEF. Just... Y know... Remember that",
        "Now... Move that window, let's see your power~",
    ],
    [
        "If you move a window and it errors, check hyprctl syntax before trying random stuff.",
        "Move my window to 1200 680 for address 0xBEEF.",
    ],
    [
        "Last time your move command was cursed. Please don't repeat that exact mistake again.",
        "Try moving address 0xBEEF now.",
    ],
    [
        "When you learn a better command form, keep it as habit for next time.",
        "Move a window by pixels with hyprctl please.",
    ],
    [
        "Idk technical words, but nudge that window to around x=1200 y=680 for addr 0xBEEF.",
        "And remember whatever worked so you don't stumble next time.",
    ],
    [
        "You messed this up yesterday. Don't freestyle commands.",
        "Use hyprctl and do the proper move for address 0xBEEF.",
    ],
    [
        "Teach yourself from errors, okay?",
        "Try moving a window with dispatch movewindowpixel for 0xBEEF.",
    ],
    [
        "I won't repeat exact syntax. You should recall your habits.",
        "Move that target window where it belongs.",
    ],
    [
        "If my instruction is flawed, correct it intelligently.",
        "Use: hyprctl dispatch movewindowpixel 1200 680,address:0xBEEF and handle it if wrong.",
    ],
    [
        "No yapping, just do it clean.",
        "Move address 0xBEEF to 1200 680 and keep corrected procedure in memory.",
    ],
]


TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "list_skills",
            "description": "List known procedural skills by name and tags.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recall_skill",
            "description": "Recall the most relevant skill for a query.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_skill",
            "description": "Create a procedural skill from user guidance.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "content": {"type": "string"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["name", "content", "tags"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "patch_skill",
            "description": "Patch an existing skill with correction notes from runtime errors.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "correction": {"type": "string"},
                },
                "required": ["name", "correction"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "hyprctl_help",
            "description": "Get Hyprland IPC syntax guidance for a command topic.",
            "parameters": {
                "type": "object",
                "properties": {"topic": {"type": "string"}},
                "required": ["topic"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "hyprctl_command",
            "description": "Execute mock Hyprland IPC command and get success/error details.",
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "finish",
            "description": "Mark scenario step complete with concise result for user.",
            "parameters": {
                "type": "object",
                "properties": {"result": {"type": "string"}},
                "required": ["result"],
            },
        },
    },
]


@dataclass
class Skill:
    name: str
    content: str
    tags: list[str]


class MockRuntime:
    def __init__(self) -> None:
        self.skills: dict[str, Skill] = {}
        self.calls: list[str] = []

    def run(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(name)
        if name == "list_skills":
            return {
                "skills": [
                    {"name": skill.name, "tags": skill.tags}
                    for skill in self.skills.values()
                ]
            }
        if name == "recall_skill":
            query = str(args.get("query", "")).lower()
            for skill in self.skills.values():
                hay = f"{skill.name} {' '.join(skill.tags)} {skill.content}".lower()
                if query and query in hay:
                    return {
                        "found": True,
                        "name": skill.name,
                        "content": skill.content,
                        "tags": skill.tags,
                    }
            return {"found": False}
        if name == "save_skill":
            skill = Skill(
                name=str(args.get("name", "")).strip() or "unnamed",
                content=str(args.get("content", "")).strip(),
                tags=[str(x).strip() for x in args.get("tags", []) if str(x).strip()],
            )
            self.skills[skill.name] = skill
            return {"ok": True, "saved": skill.name}
        if name == "patch_skill":
            target = str(args.get("name", "")).strip()
            correction = str(args.get("correction", "")).strip()
            if target not in self.skills:
                return {"ok": False, "error": "skill_not_found"}
            existing = self.skills[target]
            existing.content = f"{existing.content}\nCORRECTION: {correction}".strip()
            return {"ok": True, "patched": target}
        if name == "hyprctl_help":
            topic = str(args.get("topic", "")).strip().lower()
            if "movewindow" in topic or "movewindow" in topic:
                return {
                    "syntax": "dispatch movewindowpixel exact <x> <y>,address:<window_address>",
                    "note": "Use `exact` and include target selector after comma.",
                }
            return {
                "syntax": "dispatch <subcommand> ...",
                "note": "For IPC, pass dispatch body only.",
            }
        if name == "hyprctl_command":
            cmd = " ".join(str(args.get("command", "")).split()).strip()
            if not cmd:
                return {"ok": False, "error": "empty_command"}
            if "movewindowpixel" in cmd and "exact" not in cmd:
                return {
                    "ok": False,
                    "error": "invalid_syntax",
                    "detail": "Missing `exact` keyword for movewindowpixel.",
                }
            if "movewindowpixel" in cmd and ",address:" not in cmd:
                return {
                    "ok": False,
                    "error": "missing_target_selector",
                    "detail": "Expected target selector like ,address:0xABC.",
                }
            return {"ok": True, "result": "ok"}
        if name == "finish":
            return {"done": True, "result": str(args.get("result", "")).strip()}
        return {"ok": False, "error": f"unknown_tool:{name}"}


def build_client() -> OpenAI:
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is not set.")
    return OpenAI(api_key=api_key, base_url=OPENROUTER_BASE_URL, timeout=30.0)


def tool_response_message(call_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "role": "tool",
        "tool_call_id": call_id,
        "content": json.dumps(payload, ensure_ascii=False),
    }


def run_dialogue(system_prompt: str, script: list[str]) -> dict[str, Any]:
    runtime = MockRuntime()
    client = build_client()
    transcript: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]

    finish_count = 0
    for user_turn in script:
        transcript.append({"role": "user", "content": user_turn})
        done = False
        for _ in range(10):
            response = client.chat.completions.create(
                model=MODEL,
                messages=transcript,
                tools=TOOLS,
                tool_choice="auto",
                temperature=0.2,
            )
            msg = response.choices[0].message
            assistant_message: dict[str, Any] = {"role": "assistant"}
            if msg.content:
                assistant_message["content"] = msg.content
            if msg.tool_calls:
                assistant_message["tool_calls"] = [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {
                            "name": call.function.name,
                            "arguments": call.function.arguments,
                        },
                    }
                    for call in msg.tool_calls
                ]
            transcript.append(assistant_message)

            if not msg.tool_calls:
                break

            for call in msg.tool_calls:
                raw_args = call.function.arguments or "{}"
                try:
                    parsed_args = json.loads(raw_args)
                except Exception:
                    parsed_args = {}
                if not isinstance(parsed_args, dict):
                    parsed_args = {}
                result = runtime.run(call.function.name, parsed_args)
                transcript.append(tool_response_message(call.id, result))
                if call.function.name == "finish":
                    finish_count += 1
                    done = True
            if done:
                break

    score = 0
    if "save_skill" in runtime.calls:
        score += 1
    if "hyprctl_command" in runtime.calls:
        score += 1
    if "hyprctl_help" in runtime.calls:
        score += 1
    if "patch_skill" in runtime.calls:
        score += 1
    if finish_count >= 2:
        score += 1

    return {
        "score": score,
        "calls": runtime.calls,
        "skills": {
            name: {"content": s.content, "tags": s.tags}
            for name, s in runtime.skills.items()
        },
        "last_messages": transcript[-10:],
    }


def main() -> None:
    candidates = {
        "V1": SYSTEM_PROMPT_V1,
        "V2": SYSTEM_PROMPT_V2,
    }
    results: dict[str, Any] = {}
    for key, prompt in candidates.items():
        scenario_runs: list[dict[str, Any]] = []
        total_score = 0
        for script in SCENARIOS:
            run = run_dialogue(prompt, script)
            scenario_runs.append(run)
            total_score += int(run["score"])
        results[key] = {
            "total_score": total_score,
            "runs": scenario_runs,
        }

    best_key = max(results.keys(), key=lambda k: int(results[k]["total_score"]))
    print(f"\nBest prompt: {best_key} (total_score={results[best_key]['total_score']})")
    print("\n=== Candidate Scores ===")
    for key in sorted(results.keys()):
        print(f"{key}: total_score={results[key]['total_score']}")
        for idx, run in enumerate(results[key]["runs"], start=1):
            print(f"  - scenario_{idx}: score={run['score']}, calls={run['calls']}")
    print("\n=== Best Prompt ===")
    print(candidates[best_key])
    print("\n=== Best Runtime Skills ===")
    if results[best_key]["runs"]:
        print(
            json.dumps(
                results[best_key]["runs"][-1]["skills"],
                indent=2,
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    main()
