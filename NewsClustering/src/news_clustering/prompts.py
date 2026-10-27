from __future__ import annotations

from pathlib import Path

import yaml

PROMPTS_DIR = Path(__file__).parent / "prompts"


def load_prompts(name: str) -> dict:
    return yaml.safe_load((PROMPTS_DIR / f"{name}.yaml").read_text(encoding="utf-8"))


def render(template: str, values: dict) -> str:
    text = template
    for key, value in values.items():
        text = text.replace("{" + key + "}", str(value))
    return text
