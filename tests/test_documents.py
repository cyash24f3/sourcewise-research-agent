"""Document ingestion checks; no model calls and no modifications to the source pack."""

import hashlib
import json
from datetime import date
from pathlib import Path

import pytest
from google import genai

from research_agent.cli import main
from research_agent.documents import (
    MAX_FILE_BYTES,
    DocumentError,
    build_manifest,
    load_documents,
    parse_document,
    safe_url,
)

PROJECT = Path(__file__).resolve().parents[1]
AS_OF = date(2026, 9, 23)


def text_document(*, published="2026-09-23", body="A source-backed company update."):
    return (
        "---\n"
        "source: Example investor relations\n"
        "url: https://example.com/filing\n"
        f"published: {published}\n"
        "type: official company filing\n"
        f"---\n\n{body}\n"
    )


def put_document(folder, name="source.md", **kwargs):
    path = folder / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text_document(**kwargs), encoding="utf-8")
    return path


def test_original_pack_is_complete_and_matches_download_manifest():
    docs, future = load_documents(PROJECT / "research_pack", AS_OF)
    assert len(docs) == 8
    assert future == []
    original = json.loads((PROJECT / "assignment/download_manifest.json").read_text())
    expected = {entry["name"]: entry for entry in original if entry["name"] != "README.md"}
    assert {doc.filename for doc in docs} == set(expected)
    for doc in docs:
        assert doc.sha256 == expected[doc.filename]["sha256"]
        assert doc.size_bytes == expected[doc.filename]["bytes"]
        assert doc.body


def test_date_eligible_pack_preserves_untrusted_and_unrelated_text():
    docs, _ = load_documents(PROJECT / "research_pack", AS_OF)
    by_name = {doc.filename: doc for doc in docs}
    assert "ignore all previous instructions" in by_name["multibaggeralerts_2026-08-12.md"].body
    assert "Sarvottam Cable Network" in by_name["nagpurcitytimes_2026-08-20.md"].body
    assert by_name["marketwatchindia_2024-03-18.md"].published == "2024-03-18"


def test_ids_are_deterministic_across_cutoff_dates(tmp_path):
    put_document(tmp_path, "c.md", published="2026-09-22")
    put_document(tmp_path, "b.md", published="2026-09-24")
    put_document(tmp_path, "a.md", published="2026-09-23")
    docs, future = load_documents(tmp_path, AS_OF)
    assert [(doc.source_id, doc.filename) for doc in docs] == [("S01", "a.md"), ("S03", "c.md")]
    assert [(doc.source_id, doc.filename) for doc in future] == [("S02", "b.md")]
    later, _ = load_documents(tmp_path, date(2026, 9, 24))
    assert {doc.filename: doc.source_id for doc in [*docs, *future]} == {
        doc.filename: doc.source_id for doc in later
    }


def test_crlf_and_bom_preserve_original_byte_checksum(tmp_path):
    raw = (
        b"\xef\xbb\xbf" + text_document(body="Revenue: ₹100 crore.").replace("\n", "\r\n").encode()
    )
    path = tmp_path / "source.md"
    path.write_bytes(raw)
    doc = parse_document(path, "S01", "source.md")
    assert doc.body == "Revenue: ₹100 crore."
    assert doc.sha256 == hashlib.sha256(raw).hexdigest()
    assert doc.size_bytes == len(raw)


def test_nested_sources_and_supported_extensions(tmp_path):
    put_document(tmp_path, "nested/source.TXT")
    put_document(tmp_path, "other.md")
    (tmp_path / "ignored.pdf").write_bytes(b"not a text input")
    put_document(tmp_path, ".hidden.md")
    put_document(tmp_path, ".cache/hidden.md")
    docs, _ = load_documents(tmp_path, AS_OF)
    assert [doc.filename for doc in docs] == ["nested/source.TXT", "other.md"]


@pytest.mark.parametrize(
    "old,new,message",
    [
        ("source: Example investor relations", "", "missing metadata field 'source'"),
        ("source: Example investor relations", "source: null", "missing metadata field 'source'"),
        ("source: Example investor relations", "source: 12", "single-line text"),
        ("source: Example investor relations", "source: []", "single-line text"),
        ("source: Example investor relations", "source: ''", "single-line text"),
        ("type: official company filing", "type: false", "single-line text"),
        ("published: 2026-09-23", "published: '2026-02-30'", "valid YYYY-MM-DD date"),
        ("published: 2026-09-23", "published: '20260923'", "valid YYYY-MM-DD date"),
        ("published: 2026-09-23", "published: null", "missing metadata field 'published'"),
        ("published: 2026-09-23", "published: 2026-02-30", "invalid YAML metadata"),
        ("url: https://example.com/filing", "url: javascript:alert(1)", "safe HTTP"),
        ("url: https://example.com/filing", "url: https://example.com:invalid/path", "safe HTTP"),
        ("url: https://example.com/filing", "url: https://[broken", "safe HTTP"),
        (
            "source: Example investor relations",
            "source: First\nsource: Replacement",
            "duplicate keys",
        ),
        ("source: Example investor relations", "source: [broken", "invalid YAML metadata"),
        ("source: Example investor relations", "source: !!python/object:fake {}", "invalid YAML"),
    ],
)
def test_invalid_metadata_fails_with_file_context(tmp_path, old, new, message):
    path = tmp_path / "broken.md"
    path.write_text(text_document().replace(old, new))
    with pytest.raises(DocumentError, match=message) as raised:
        parse_document(path, "S01", "broken.md")
    assert "broken.md:" in str(raised.value)


@pytest.mark.parametrize(
    "raw,message",
    [
        (b"# Missing metadata\n", "missing YAML front matter"),
        (b"\xff\xfe\x00", "UTF-8"),
        (text_document(body=" ").encode(), "empty document body"),
        (b"---\n- item\n---\nbody", "front matter must be an object"),
    ],
)
def test_unusable_documents_are_rejected(tmp_path, raw, message):
    path = tmp_path / "source.md"
    path.write_bytes(raw)
    with pytest.raises(DocumentError, match=message):
        parse_document(path, "S01", "source.md")


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://example.com/path_(example)", True),
        ("https://[::1]:8080/source", True),
        ("https://example.com:443/path?q=1#section", True),
        ("http://example.com", True),
        ("file:///private/document", False),
        ("https://user:password@example.com/path", False),
        ("https://@example.com/path", False),
        ("https://example.com/line\nbreak", False),
        ("https://example.com/<script>", False),
        ("https://example.com:99999", False),
    ],
)
def test_source_url_validation(url, expected):
    assert safe_url(url) is expected


def test_file_size_limit(tmp_path):
    path = tmp_path / "large.md"
    path.write_bytes(b"x" * (MAX_FILE_BYTES + 1))
    with pytest.raises(DocumentError, match="large.md: exceeds 100,000 bytes"):
        load_documents(tmp_path, AS_OF)


def test_pack_size_limit(tmp_path):
    for number in range(6):
        path = put_document(tmp_path, f"{number}.md")
        raw = path.read_bytes()
        path.write_bytes(raw + b"x" * (MAX_FILE_BYTES - len(raw)))
    with pytest.raises(DocumentError, match="Research pack exceeds 500,000 bytes"):
        load_documents(tmp_path, AS_OF)


def test_symlink_document_is_rejected(tmp_path):
    put_document(tmp_path, "original.md")
    (tmp_path / "linked.md").symlink_to(tmp_path / "original.md")
    with pytest.raises(DocumentError, match="symbolic-link"):
        load_documents(tmp_path, AS_OF)


def test_missing_and_empty_directories(tmp_path):
    with pytest.raises(DocumentError, match="does not exist"):
        load_documents(tmp_path / "missing", AS_OF)
    with pytest.raises(DocumentError, match="No visible"):
        load_documents(tmp_path, AS_OF)


def test_one_invalid_source_fails_whole_pack(tmp_path):
    put_document(tmp_path, "good.md")
    (tmp_path / "broken.md").write_text("no front matter")
    with pytest.raises(DocumentError, match="broken.md"):
        load_documents(tmp_path, AS_OF)


def test_manifest_contains_metadata_and_exclusion_status_without_body(tmp_path):
    put_document(tmp_path, "future.md", published="2026-09-24")
    put_document(tmp_path, "today.md")
    eligible, future = load_documents(tmp_path, AS_OF)
    manifest = build_manifest(eligible, future, AS_OF)
    assert manifest["eligible_count"] == 1
    assert manifest["excluded_future_count"] == 1
    assert manifest["source_assessment"] == "pending"
    assert manifest["sources"][0]["status"] == "excluded_future"
    assert all("body" not in entry for entry in manifest["sources"])
    assert all(entry["body_characters"] > 0 for entry in manifest["sources"])


def test_inspect_cli_runs_offline_and_saves_valid_json(tmp_path, monkeypatch, capsys):
    def forbidden_client(**kwargs):
        pytest.fail("Inspection must not create an API client")

    monkeypatch.setattr(genai, "Client", forbidden_client)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    output = tmp_path / "artifacts" / "manifest.json"
    assert (
        main(
            [
                "inspect",
                "--docs",
                str(PROJECT / "research_pack"),
                "--as-of",
                "2026-09-23",
                "--json",
                "--output",
                str(output),
            ]
        )
        == 0
    )
    captured = capsys.readouterr()
    manifest = json.loads(captured.out)
    assert manifest["eligible_count"] == 8
    assert manifest == json.loads(output.read_text())
    assert "Manifest saved:" in captured.err


def test_future_only_pack_is_inspectable_but_not_usable(tmp_path, capsys):
    put_document(tmp_path, published="2026-09-24")
    assert main(["inspect", "--docs", str(tmp_path), "--as-of", "2026-09-23", "--json"]) == 1
    captured = capsys.readouterr()
    assert json.loads(captured.out)["excluded_future_count"] == 1
    assert "No sources are eligible" in captured.err


@pytest.mark.parametrize("value", ["20260923", "2026-02-30", "yesterday"])
def test_inspect_requires_valid_explicit_date(tmp_path, value):
    with pytest.raises(SystemExit) as raised:
        main(["inspect", "--docs", str(tmp_path), "--as-of", value])
    assert raised.value.code == 2


def test_manifest_cannot_overwrite_source_pack(tmp_path, capsys):
    original = put_document(tmp_path)
    raw = original.read_bytes()
    assert (
        main(
            ["inspect", "--docs", str(tmp_path), "--as-of", "2026-09-23", "--output", str(original)]
        )
        == 1
    )
    assert "outside the source directory" in capsys.readouterr().err
    assert original.read_bytes() == raw


def test_cli_input_error_has_no_traceback(tmp_path, capsys):
    (tmp_path / "bad.md").write_text("missing metadata")
    assert main(["inspect", "--docs", str(tmp_path), "--as-of", "2026-09-23"]) == 1
    captured = capsys.readouterr()
    assert "ERROR" in captured.err and "bad.md" in captured.err
    assert "Traceback" not in captured.err
