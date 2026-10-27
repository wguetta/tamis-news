from __future__ import annotations

import json
import time

from openai import OpenAI

from editorial.config import EditorialConfig


class LlmClient:
    """Single OpenAI wrapper. complete() returns parsed JSON if a schema is given, else text."""

    def __init__(self, config: EditorialConfig):
        self.config = config
        self.client = OpenAI(api_key=config.openai_api_key, timeout=config.llm_timeout_seconds)
        self.last_usage = None

    def complete(
        self,
        instructions: str,
        user: str,
        schema: dict | None = None,
        schema_name: str = "response",
        model: str | None = None,
    ):
        preferred = model or self.config.editorial_model
        models = [preferred]
        if self.config.fallback_model and self.config.fallback_model not in models:
            models.append(self.config.fallback_model)

        last_error = None
        for model_name in models:
            for attempt in range(self.config.llm_max_retries + 1):
                try:
                    return self._once(instructions, user, schema, schema_name, model_name)
                except Exception as exc:
                    last_error = exc
                    if attempt < self.config.llm_max_retries:
                        time.sleep(1.5 * (2**attempt))
        raise RuntimeError(f"LLM call failed: {last_error}") from last_error

    def _once(self, instructions, user, schema, schema_name, model):
        kwargs = {"model": model, "instructions": instructions, "input": user}
        if schema is not None:
            kwargs["text"] = {
                "format": {
                    "type": "json_schema",
                    "name": schema_name,
                    "strict": True,
                    "schema": schema,
                }
            }
        response = self.client.responses.create(**kwargs)
        self.last_usage = getattr(response, "usage", None)
        text = response.output_text or ""
        if not text.strip():
            raise RuntimeError("OpenAI returned an empty response")
        if schema is None:
            return text
        data = json.loads(text)
        if not isinstance(data, dict):
            raise RuntimeError("Model output must be a JSON object")
        return data
