"""Read Gemini settings without changing the process environment or exposing keys."""

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values

GEMINI_MODEL = "gemini-3.8-flash"


class ConfigurationError(ValueError):
    """Configuration needs attention before a request can be made."""


@dataclass(frozen=True)
class GeminiSettings:
    api_key: str = field(repr=False)
    key_source: str
    model: str = GEMINI_MODEL


def load_settings(project_dir: Path, *, require_key: bool = True) -> GeminiSettings:
    env_path = project_dir / ".env"
    try:
        # Disable variable expansion: do not accidentally reinterpret characters in a key.
        local = dotenv_values(env_path, interpolate=False) if env_path.is_file() else {}
    except OSError as exc:
        raise ConfigurationError("Cannot read the local .env file.") from exc

    key, source = "", "not configured"
    for values, location in ((os.environ, "environment"), (local, ".env")):
        for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
            candidate = str(values.get(name) or "").strip()
            if candidate:
                key, source = candidate, f"{location}: {name}"
                break
        if key:
            break
    model = str(os.environ.get("GEMINI_MODEL") or local.get("GEMINI_MODEL") or GEMINI_MODEL)
    model = model.strip()
    if model != GEMINI_MODEL:
        raise ConfigurationError(
            f"Set GEMINI_MODEL={GEMINI_MODEL}; this build uses the selected model."
        )
    if require_key and not key:
        raise ConfigurationError(
            "Gemini API key missing. Add GEMINI_API_KEY to the local .env file "
            "or set it in the environment. Keep the key out of chat and Git."
        )
    return GeminiSettings(api_key=key, key_source=source, model=model)
