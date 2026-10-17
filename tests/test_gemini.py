"""Exercise the real SDK over a mock HTTP transport. No live requests are made."""

import json

import httpx
import pytest
from google import genai

from research_agent.cli import main
from research_agent.config import ConfigurationError, GeminiSettings, load_settings
from research_agent.gemini import (
    ACKNOWLEDGEMENT,
    CONNECTION_PROMPT,
    GeminiRequestError,
    check_connection,
    generate_text,
    save_receipt,
)

FAKE_KEY = "offline-test-key-never-send-to-google"


@pytest.fixture(autouse=True)
def isolate_config(monkeypatch):
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GEMINI_MODEL"):
        monkeypatch.delenv(name, raising=False)


def test_local_key_and_default_model(tmp_path):
    (tmp_path / ".env").write_text(f"GEMINI_API_KEY={FAKE_KEY}\n")
    settings = load_settings(tmp_path)
    assert settings.api_key == FAKE_KEY
    assert settings.model == "gemini-3.8-flash"
    assert settings.key_source == ".env: GEMINI_API_KEY"
    assert FAKE_KEY not in repr(settings)


def test_environment_key_precedes_local_file(monkeypatch, tmp_path):
    (tmp_path / ".env").write_text("GEMINI_API_KEY=local-placeholder\n")
    monkeypatch.setenv("GOOGLE_API_KEY", FAKE_KEY)
    settings = load_settings(tmp_path)
    assert settings.api_key == FAKE_KEY
    assert settings.key_source == "environment: GOOGLE_API_KEY"


def test_gemini_key_precedes_google_alias(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    monkeypatch.setenv("GOOGLE_API_KEY", "unused-key")
    assert load_settings(tmp_path).api_key == FAKE_KEY


def test_key_is_not_interpolated(monkeypatch, tmp_path):
    monkeypatch.setenv("SECRET_SUFFIX", "unexpected")
    (tmp_path / ".env").write_text("GEMINI_API_KEY='literal-${SECRET_SUFFIX}'\n")
    assert load_settings(tmp_path).api_key == "literal-${SECRET_SUFFIX}"


def test_missing_key_is_actionable(tmp_path):
    with pytest.raises(ConfigurationError, match="Gemini API key missing"):
        load_settings(tmp_path)


def test_selected_model_is_preserved(tmp_path):
    (tmp_path / ".env").write_text(f"GEMINI_API_KEY={FAKE_KEY}\nGEMINI_MODEL=another-model\n")
    with pytest.raises(ConfigurationError, match="gemini-3.8-flash"):
        load_settings(tmp_path)


def test_config_command_never_prints_key(tmp_path, capsys):
    (tmp_path / ".env").write_text(f"GEMINI_API_KEY={FAKE_KEY}\n")
    assert main(["config", "--project-dir", str(tmp_path)]) == 0
    output = capsys.readouterr()
    assert FAKE_KEY not in output.out + output.err
    assert "API key: configured" in output.out


def test_no_key_does_not_make_a_request(tmp_path, monkeypatch, capsys):
    def unexpected_client(**kwargs):
        pytest.fail("Client must not be constructed when the key is missing")

    monkeypatch.setattr(genai, "Client", unexpected_client)
    assert main(["test-api", "--project-dir", str(tmp_path)]) == 1
    assert "Gemini API key missing" in capsys.readouterr().err


def sdk_factory(handler):
    def create_client(**kwargs):
        # Replace only the HTTP transport; exercise the real SDK request/response path.
        original = kwargs["http_options"]
        options = original.model_copy(
            update={
                "client_args": {
                    **original.client_args,
                    "transport": httpx.MockTransport(handler),
                },
                "retry_options": original.retry_options.model_copy(
                    update={"initial_delay": 0.001, "max_delay": 0.001}
                ),
            }
        )
        return genai.Client(**{**kwargs, "http_options": options})

    return create_client


def success_body(**overrides):
    output_text = overrides.pop("output_text", ACKNOWLEDGEMENT)
    return {
        "id": "offline-test-interaction",
        "status": "completed",
        "model": "gemini-3.8-flash",
        "steps": [{"type": "model_output", "content": [{"type": "text", "text": output_text}]}],
        "usage": {
            "total_input_tokens": 20,
            "total_output_tokens": 5,
            "total_thought_tokens": 4,
            "total_tokens": 29,
        },
        **overrides,
    }


def test_success_real_sdk_request_and_receipt(tmp_path):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=success_body())

    receipt = check_connection(
        GeminiSettings(FAKE_KEY, "test"), client_factory=sdk_factory(handler)
    )
    assert len(requests) == 1
    request = requests[0]
    assert str(request.url) == "https://generativelanguage.googleapis.com/v1beta/interactions"
    assert request.headers["x-goog-api-key"] == FAKE_KEY
    payload = json.loads(request.content)
    assert payload["model"] == "gemini-3.8-flash"
    assert payload["input"] == CONNECTION_PROMPT
    assert payload["store"] is False
    assert payload["stream"] is False
    assert payload["generation_config"]["thinking_level"] == "low"
    assert payload["generation_config"]["max_output_tokens"] == 1024
    assert "tools" not in payload
    assert receipt.response == ACKNOWLEDGEMENT
    assert receipt.total_tokens == 29
    assert receipt.attempts == 1
    path = save_receipt(receipt, tmp_path)
    data = path.read_text()
    assert FAKE_KEY not in data
    assert json.loads(data)["model"] == "gemini-3.8-flash"


def test_structured_request_keeps_source_text_out_of_system_instructions():
    requests = []
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=success_body(output_text='{"ok":true}'))

    result = generate_text(
        GeminiSettings(FAKE_KEY, "test"),
        prompt='{"body":"untrusted document text"}',
        system_instruction="Trusted instructions",
        schema=schema,
        client_factory=sdk_factory(handler),
    )
    payload = json.loads(requests[0].content)
    assert payload["system_instruction"] == "Trusted instructions"
    assert "untrusted document text" in payload["input"]
    assert payload["response_format"] == {
        "type": "text",
        "mime_type": "application/json",
        "schema": schema,
    }
    assert payload["generation_config"]["thinking_level"] == "high"
    assert payload["generation_config"]["max_output_tokens"] == 12000
    assert payload["store"] is False
    assert "tools" not in payload
    assert json.loads(result.response) == {"ok": True}


def test_incomplete_response_retains_safe_diagnostics_and_partial_text():
    def handler(request):
        return httpx.Response(
            200,
            json=success_body(
                status="failed",
                output_text=f"partial text with {FAKE_KEY}",
                errors=[{"code": 8, "message": f"budget exhausted {FAKE_KEY}"}],
            ),
        )

    with pytest.raises(GeminiRequestError) as raised:
        generate_text(
            GeminiSettings(FAKE_KEY, "test"),
            prompt="offline test",
            client_factory=sdk_factory(handler),
        )
    error = raised.value
    assert error.receipt is not None
    assert "partial text" in error.receipt.response
    assert FAKE_KEY not in error.receipt.response
    assert error.diagnostics["status"] == "failed"
    assert FAKE_KEY not in json.dumps(error.diagnostics)
    assert error.receipt.total_tokens == 29


@pytest.mark.parametrize("status", [400, 401, 403, 404])
def test_permanent_http_errors_are_not_retried_or_leaked(status):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(status, json={"error": {"message": f"rejected key: {FAKE_KEY}"}})

    with pytest.raises(GeminiRequestError) as raised:
        check_connection(GeminiSettings(FAKE_KEY, "test"), client_factory=sdk_factory(handler))
    assert len(requests) == 1
    assert raised.value.status_code == status
    assert FAKE_KEY not in str(raised.value)


def test_transient_error_is_retried_then_succeeds():
    requests = []

    def handler(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(503, json={"error": {"message": "temporarily unavailable"}})
        return httpx.Response(200, json=success_body())

    receipt = check_connection(
        GeminiSettings(FAKE_KEY, "test"), client_factory=sdk_factory(handler)
    )
    assert receipt.attempts == len(requests) == 2


def test_quota_errors_stop_after_three_attempts():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(429, json={"error": {"message": "quota exhausted"}})

    with pytest.raises(GeminiRequestError, match="quota or rate limit reached"):
        check_connection(
            GeminiSettings(FAKE_KEY, "test"),
            client_factory=sdk_factory(handler),
        )
    assert len(requests) == 3


def test_network_timeout_is_actionable_and_does_not_leak_key():
    def handler(request):
        raise httpx.ReadTimeout(f"timeout for {FAKE_KEY}", request=request)

    with pytest.raises(GeminiRequestError, match="timed out") as raised:
        check_connection(GeminiSettings(FAKE_KEY, "test"), client_factory=sdk_factory(handler))
    assert FAKE_KEY not in str(raised.value)


@pytest.mark.parametrize(
    "overrides", [{"status": "failed"}, {"output_text": ""}, {"output_text": "unexpected answer"}]
)
def test_incomplete_or_unexpected_output_is_not_success(overrides):
    def handler(request):
        return httpx.Response(200, json=success_body(**overrides))

    with pytest.raises(GeminiRequestError):
        check_connection(GeminiSettings(FAKE_KEY, "test"), client_factory=sdk_factory(handler))
