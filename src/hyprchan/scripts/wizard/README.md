# Wizard Framework

Mini setup framework for Hyprchan onboarding and extension setup.

## Prompt UX

- Uses `questionary` by default for popup-style terminal prompts.
- Single-choice `Choice(..., multiple=False)` renders as a radio-like select list.
- Multi-choice `Choice(..., multiple=True)` renders as checkbox list (`Space` to toggle).
- `Confirm` renders as yes/no toggle.
- `Input` and `SecretInput` use text/password prompt fields.

## Quick Shape

- Define a wizard by subclassing `Wizard`.
- Register steps with `@step(name=..., description=...)`.
- Use annotated inputs in step parameters:
  - `Annotated[str, Input(...)]`
  - `Annotated[str, Choice([...])]`
  - `Annotated[bool, Confirm(...)]`
  - `Annotated[str, SecretInput(...)]`
- Add dynamic steps during runtime with `ctx.add_step(...)`.

## Example

```python
from typing import Annotated

from scripts.wizard import Choice, Input, MainInstaller, WizardContext, step


class DemoInstaller(MainInstaller):
    @step(name="Provider", description="Pick your AI provider")
    def provider_step(
        self,
        ctx: WizardContext,
        provider: Annotated[str, Choice(["openai", "openrouter", "gemini"])],
    ) -> dict[str, str]:
        return {"provider": provider}

    @step(name="Nickname", description="Set assistant nickname")
    def nickname_step(
        self,
        nickname: Annotated[str, Input(placeholder="Hyprchan", required=False)],
    ) -> dict[str, str]:
        return {"nickname": nickname}
```

Run with:

```python
result = DemoInstaller().run_sync()
```
