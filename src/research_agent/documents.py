"""Load small UTF-8 research packs. Source URLs are labels, never instructions to fetch."""

import hashlib
import re
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

import yaml

MAX_FILE_BYTES = 100_000
MAX_PACK_BYTES = 500_000


class DocumentError(ValueError):
    """An input file or research pack cannot be used as supplied."""


class MetadataLoader(yaml.SafeLoader):
    """Reject ambiguous duplicate keys instead of silently taking the last value."""

    def construct_mapping(self, node, deep=False):
        mapping = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str) or key in mapping:
                raise yaml.constructor.ConstructorError(
                    None, None, "Metadata keys must be unique strings", key_node.start_mark
                )
            mapping[key] = self.construct_object(value_node, deep=deep)
        return mapping


@dataclass(frozen=True)
class Document:
    source_id: str
    filename: str
    source: str
    url: str
    published: str
    source_type: str
    body: str
    sha256: str
    size_bytes: int

    def as_dict(self) -> dict:
        return asdict(self)


def safe_url(value: str) -> bool:
    """Block executable URLs and characters that break generated Markdown links."""
    try:
        parts = urlsplit(value)
        # Accessing port validates malformed/non-numeric ports as well.
        port = parts.port
        return (
            parts.scheme in {"https", "http"}
            and bool(parts.hostname)
            and parts.username is None
            and parts.password is None
            and (port is None or 0 < port <= 65535)
            and not re.search(r"[\s<>\\\x00-\x1f\x7f]", value)
        )
    except ValueError:
        return False


def parse_date(value: str) -> date:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("Use a valid date in YYYY-MM-DD format.")
    return date.fromisoformat(value)


def parse_document(path: Path, source_id: str, filename: str) -> Document:
    if path.is_symlink():
        raise DocumentError(f"{filename}: symbolic-link documents are not supported.")
    try:
        with path.open("rb") as stream:
            raw = stream.read(MAX_FILE_BYTES + 1)
    except OSError as exc:
        raise DocumentError(f"{filename}: cannot read the document.") from exc
    if len(raw) > MAX_FILE_BYTES:
        raise DocumentError(
            f"{filename}: exceeds {MAX_FILE_BYTES:,} bytes; split the document first."
        )
    try:
        text = raw.decode("utf-8-sig").replace("\r\n", "\n")
    except UnicodeDecodeError as exc:
        raise DocumentError(f"{filename}: must be a UTF-8 text document.") from exc
    match = re.match(r"\A---\n(.*?)\n---(?:\n|$)(.*)\Z", text, re.DOTALL)
    if not match:
        raise DocumentError(
            f"{filename}: missing YAML front matter (source, url, published, type)."
        )
    try:
        meta = yaml.load(match[1], Loader=MetadataLoader)
    except (yaml.YAMLError, ValueError) as exc:
        raise DocumentError(
            f"{filename}: invalid YAML metadata; check dates, syntax, and duplicate keys."
        ) from exc
    if not isinstance(meta, dict):
        raise DocumentError(f"{filename}: front matter must be an object.")
    for field in ("source", "url", "published", "type"):
        if field not in meta or meta[field] is None:
            raise DocumentError(f"{filename}: missing metadata field '{field}'.")
    for field in ("source", "url", "type"):
        value = meta[field]
        if not isinstance(value, str) or not value.strip() or re.search(r"[\x00-\x1f\x7f]", value):
            raise DocumentError(f"{filename}: '{field}' must be non-empty, single-line text.")
    try:
        published = parse_date(str(meta["published"])).isoformat()
    except ValueError as exc:
        raise DocumentError(f"{filename}: 'published' must be a valid YYYY-MM-DD date.") from exc
    url = meta["url"].strip()
    if not safe_url(url):
        raise DocumentError(f"{filename}: source URL must be a safe HTTP(S) URL.")
    body = match[2].strip()
    if not body:
        raise DocumentError(f"{filename}: empty document body.")
    return Document(
        source_id=source_id,
        filename=filename,
        source=meta["source"].strip(),
        url=url,
        published=published,
        source_type=meta["type"].strip(),
        body=body,
        sha256=hashlib.sha256(raw).hexdigest(),
        size_bytes=len(raw),
    )


def load_documents(folder: Path, as_of: date) -> tuple[list[Document], list[Document]]:
    """Return date-eligible documents and future documents separately.

    Eligibility is not a relevance or reliability judgement. All supported files
    must parse successfully; invalid files fail the whole pack rather than being
    silently skipped. Future-only packs return an empty eligible list for inspection.
    """
    if not folder.is_dir():
        raise DocumentError(f"Document directory does not exist: {folder}")
    paths = sorted(
        (
            p
            for p in folder.rglob("*")
            if p.is_file()
            and p.suffix.lower() in {".md", ".txt"}
            and not any(part.startswith(".") for part in p.relative_to(folder).parts)
        ),
        key=lambda p: p.relative_to(folder).as_posix(),
    )
    if not paths:
        raise DocumentError("No visible .md or .txt documents found.")
    eligible, future = [], []
    total_bytes = 0
    for number, path in enumerate(paths, start=1):
        doc = parse_document(path, f"S{number:02}", path.relative_to(folder).as_posix())
        total_bytes += doc.size_bytes
        if total_bytes > MAX_PACK_BYTES:
            raise DocumentError(
                f"Research pack exceeds {MAX_PACK_BYTES:,} bytes; use a smaller pack."
            )
        (eligible if date.fromisoformat(doc.published) <= as_of else future).append(doc)
    return eligible, future


def build_manifest(eligible: list[Document], future: list[Document], as_of: date) -> dict:
    """Create an inspection manifest without copying document bodies into the report."""
    future_ids = {doc.source_id for doc in future}
    sources = []
    for doc in sorted([*eligible, *future], key=lambda item: item.filename):
        entry = doc.as_dict()
        entry.pop("body")
        entry["body_characters"] = len(doc.body)
        entry["status"] = "excluded_future" if doc.source_id in future_ids else "eligible"
        sources.append(entry)
    return {
        "as_of": as_of.isoformat(),
        "eligible_count": len(eligible),
        "excluded_future_count": len(future),
        "total_bytes": sum(doc.size_bytes for doc in [*eligible, *future]),
        "source_assessment": "pending",
        "sources": sources,
    }
