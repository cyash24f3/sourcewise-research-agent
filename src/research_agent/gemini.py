"""Bounded Gemini requests using the official Google SDK, with request receipts."""

import json
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import httpx
from google import genai
from google.genai import types

from .config import GeminiSettings

ACKNOWLEDGEMENT = "GEMINI_CONNECTION_OK"
CONNECTION_PROMPT = f"Reply with exactly this text and nothing else: {ACKNOWLEDGEMENT}"
RETRYABLE_CODES = {408, 429, 500, 502, 503, 504}
MAX_ATTEMPTS = 3
TIMEOUT_SECONDS = 30


class GeminiRequestError(RuntimeError):
    """Safe user-facing error. Never includes raw provider messages or credentials."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        receipt: "ConnectionReceipt | None" = None,
        diagnostics: dict | None = None,
    ):
        self.status_code = status_code
        self.receipt = receipt
        self.diagnostics = diagnostics
        super().__init__(message)


@dataclass(frozen=True)
class ConnectionReceipt:
    checked_at_utc: str
    provider: str
    model: str
    returned_model: str | None
    interaction_id: str | None
    response: str
    elapsed_seconds: float
    attempts: int
    input_tokens: int | None
    output_tokens: int | None
    thought_tokens: int | None
    total_tokens: int | None


def safe_request_error(exc: Exception) -> GeminiRequestError:
    # Interactions and generateContent use different SDK exception classes.
    # Read their public status fields and never print str(exc), which can contain secrets.
    status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    if not isinstance(status, int):
        status = None
    messages = {
        400: "Gemini rejected the request. Check the API key and the installed SDK version.",
        401: "Gemini authentication failed. Check the API key in the project's .env file.",
        403: "Gemini access denied. Check the key's permissions, project, and region eligibility.",
        404: "Gemini 3.8 Flash is unavailable to this project or API endpoint. "
        "No model was substituted.",
        408: "Gemini request timed out. Try again after checking the network.",
        429: "Gemini quota or rate limit reached. Check your Free-tier limits in AI Studio "
        "and retry after the quota resets; billing was not changed.",
    }
    if status in messages:
        return GeminiRequestError(messages[status], status_code=status)
    if status and status >= 500:
        return GeminiRequestError(
            "Gemini is temporarily unavailable. Retry later.", status_code=status
        )
    if isinstance(exc, (httpx.TimeoutException, TimeoutError)) or "Timeout" in type(exc).__name__:
        return GeminiRequestError("Gemini request timed out. Check the network and retry.")
    if isinstance(exc, httpx.TransportError) or "Connection" in type(exc).__name__:
        return GeminiRequestError("Cannot reach Gemini. Check your network and retry.")
    return GeminiRequestError(
        "Gemini request failed before a usable response. Check your network and SDK configuration.",
        status_code=status,
    )


def generate_text(
    settings: GeminiSettings,
    *,
    prompt: str,
    system_instruction: str | None = None,
    schema: dict | None = None,
    thinking_level: str = "high",
    max_output_tokens: int = 12000,
    timeout_seconds: int = 90,
    client_factory: Callable | None = None,
) -> ConnectionReceipt:
    """Make one logical request with at most three actual HTTP sends and no tools."""
    factory = client_factory or genai.Client
    start = time.monotonic()
    attempts = 0

    def count_request(request: httpx.Request) -> None:
        nonlocal attempts
        attempts += 1

    # Interactions treats this option as a retry count; the initial request is additional.
    # Count actual HTTP sends, and use one retry layer to preserve the three-attempt cap.
    options = types.HttpOptions(
        api_version="v1beta",
        timeout=timeout_seconds * 1000,
        client_args={"event_hooks": {"request": [count_request]}},
        retry_options=types.HttpRetryOptions(
            attempts=MAX_ATTEMPTS - 1,
            initial_delay=1,
            max_delay=2,
            jitter=0,
            http_status_codes=sorted(RETRYABLE_CODES),
        ),
    )
    try:
        client = factory(api_key=settings.api_key, vertexai=False, http_options=options)
    except Exception as exc:
        raise safe_request_error(exc) from None

    with client:
        try:
            extra = {}
            if system_instruction is not None:
                extra["system_instruction"] = system_instruction
            if schema is not None:
                extra["response_format"] = {
                    "type": "text",
                    "mime_type": "application/json",
                    "schema": schema,
                }
            interaction = client.interactions.create(
                model=settings.model,
                input=prompt,
                store=False,
                stream=False,
                generation_config={
                    "max_output_tokens": max_output_tokens,
                    "thinking_level": thinking_level,
                    "thinking_summaries": "none",
                },
                timeout=timeout_seconds,
                **extra,
            )
        except Exception as exc:
            raise safe_request_error(exc) from None

    text = (interaction.output_text or "").strip()
    text = text.replace(settings.api_key, "[REDACTED]")
    usage = interaction.usage
    receipt = ConnectionReceipt(
        checked_at_utc=datetime.now(timezone.utc).isoformat(),
        provider="Google Gemini Developer API",
        model=settings.model,
        returned_model=interaction.model,
        interaction_id=interaction.id,
        response=text,
        elapsed_seconds=round(time.monotonic() - start, 3),
        attempts=attempts,
        input_tokens=usage.total_input_tokens if usage else None,
        output_tokens=usage.total_output_tokens if usage else None,
        thought_tokens=usage.total_thought_tokens if usage else None,
        total_tokens=usage.total_tokens if usage else None,
    )
    if interaction.status != "completed" or not text:
        diagnostics = {
            "status": str(interaction.status),
            "errors": [
                {
                    "code": getattr(error, "code", None),
                    "message": str(getattr(error, "message", "")).replace(
                        settings.api_key, "[REDACTED]"
                    )[:1000],
                }
                for error in (interaction.errors or [])
            ],
        }
        raise GeminiRequestError(
            "Gemini did not return completed text. No validated result was saved.",
            receipt=receipt,
            diagnostics=diagnostics,
        )
    return receipt


def check_connection(
    settings: GeminiSettings, *, client_factory: Callable | None = None
) -> ConnectionReceipt:
    result = generate_text(
        settings,
        prompt=CONNECTION_PROMPT,
        thinking_level="low",
        max_output_tokens=1024,
        timeout_seconds=TIMEOUT_SECONDS,
        client_factory=client_factory,
    )
    if result.response != ACKNOWLEDGEMENT:
        raise GeminiRequestError(
            "Gemini responded, but did not return the expected acknowledgement. "
            "No success receipt was saved."
        )
    return result


def save_receipt(receipt: ConnectionReceipt, project_dir: Path) -> Path:
    folder = project_dir / "artifacts" / "api_checks"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"gemini-{uuid.uuid4().hex[:12]}.json"
    path.write_text(json.dumps(asdict(receipt), indent=2) + "\n", encoding="utf-8")
    return path
