"""Smoke tests for the installed CLI; no API requests or credentials needed."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from research_agent.cli import main

PROJECT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "command",
    [
        ["research", "--help"],
        ["research", "--version"],
        [sys.executable, "-m", "research_agent", "--help"],
    ],
)
def test_installed_entry_points(command):
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert "research" in result.stdout.lower()


def test_setup_check_works_without_api_key(monkeypatch, capsys):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    assert main(["check", "--project-dir", str(PROJECT)]) == 0
    output = capsys.readouterr().out
    assert "8 document files" in output
    assert "This command does not test API connectivity" in output


def test_setup_check_reports_missing_project(tmp_path, capsys):
    assert main(["check", "--project-dir", str(tmp_path)]) == 1
    output = capsys.readouterr().out
    assert "FAIL  pyproject.toml: missing" in output
    assert "FAIL  Research pack: 0 document files" in output


def test_installed_command_from_another_directory(tmp_path):
    # Exercise the packaged console script, rather than depending on the source cwd.
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env.pop("GEMINI_API_KEY", None)
    env.pop("GOOGLE_API_KEY", None)
    result = subprocess.run(
        ["research", "check", "--project-dir", str(PROJECT)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Local setup is ready" in result.stdout
