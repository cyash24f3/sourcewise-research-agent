"""Command-line entry point. Setup checks run locally without an API key."""

import argparse
import importlib
import json
import platform
import sys
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from .config import ConfigurationError, load_settings
from .documents import DocumentError, build_manifest, load_documents, parse_date

DISTRIBUTION = "sourcewise-research"
DEPENDENCIES = {
    "google-genai": "google.genai",
    "httpx": "httpx",
    "pydantic": "pydantic",
    "python-dotenv": "dotenv",
    "PyYAML": "yaml",
}


@dataclass(frozen=True)
class SetupCheck:
    name: str
    passed: bool
    detail: str


def package_version() -> str:
    try:
        return version(DISTRIBUTION)
    except PackageNotFoundError:
        return "not installed"


def check_setup(project_dir: Path) -> list[SetupCheck]:
    checks = [SetupCheck("Python", sys.version_info >= (3, 10), platform.python_version())]
    for distribution, module in DEPENDENCIES.items():
        try:
            importlib.import_module(module)
            installed_version = version(distribution)
        except (ImportError, PackageNotFoundError):
            checks.append(SetupCheck(distribution, False, "missing; run uv sync --extra dev"))
        else:
            checks.append(SetupCheck(distribution, True, installed_version))

    for filename in (
        "pyproject.toml",
        "README.md",
        ".env.example",
        "src/research_agent/prompts/evidence_v5.md",
        "src/research_agent/prompts/writer_v5.md",
        "src/research_agent/prompts/review_v1.md",
    ):
        exists = (project_dir / filename).is_file()
        checks.append(SetupCheck(filename, exists, "present" if exists else "missing"))

    pack = project_dir / "research_pack"
    documents = [
        path
        for path in pack.rglob("*")
        if path.is_file() and path.suffix.lower() in {".md", ".txt"}
    ]
    checks.append(SetupCheck("Research pack", bool(documents), f"{len(documents)} document files"))
    return checks


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="research",
        description="SourceWise: company research briefs grounded in supplied documents.",
        epilog="Use config to inspect settings locally, then test-api to verify Gemini access.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {package_version()}")
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser(
        "check", help="Check the local project setup without calling an API"
    )
    check.add_argument(
        "--project-dir",
        type=Path,
        default=Path.cwd(),
        help="Project directory to check (default: current directory)",
    )
    config = commands.add_parser(
        "config", help="Show Gemini configuration without displaying the key"
    )
    config.add_argument("--project-dir", type=Path, default=Path.cwd())
    api_test = commands.add_parser("test-api", help="Make a small Gemini API connection test")
    api_test.add_argument("--project-dir", type=Path, default=Path.cwd())
    inspect = commands.add_parser(
        "inspect", help="Validate and inspect documents without an API call"
    )
    inspect.add_argument(
        "--docs", type=Path, required=True, help="Directory of .md or .txt sources"
    )
    inspect.add_argument(
        "--as-of", type=research_date, required=True, help="Research date in YYYY-MM-DD format"
    )
    inspect.add_argument("--json", action="store_true", help="Print the metadata manifest as JSON")
    inspect.add_argument("--output", type=Path, help="Also save the manifest as a JSON file")
    extract = commands.add_parser(
        "extract", help="Assess sources and extract a cited evidence ledger"
    )
    extract.add_argument("--ticker", required=True)
    extract.add_argument(
        "--company", help="Full company name to help distinguish similarly named entities"
    )
    extract.add_argument("--docs", type=Path, required=True)
    extract.add_argument("--as-of", type=research_date, required=True)
    extract.add_argument("--project-dir", type=Path, default=Path.cwd())
    extract.add_argument(
        "--output-root", type=Path, help="Parent directory for unique evidence runs"
    )
    run = commands.add_parser("run", help="Run source assessment and generate a cited brief")
    run.add_argument("--ticker", required=True)
    run.add_argument("--company")
    run.add_argument("--docs", type=Path, required=True)
    run.add_argument("--as-of", type=research_date, required=True)
    run.add_argument("--project-dir", type=Path, default=Path.cwd())
    run.add_argument("--output-root", type=Path)
    run.add_argument("--export-dir", type=Path, help="Save the brief and evidence for review")
    run.add_argument(
        "--writer-version",
        choices=["writer_v5"],
        default="writer_v5",
    )
    run.add_argument(
        "--evidence-run",
        type=Path,
        help="Reuse matching saved evidence; omit for a complete fresh run",
    )
    return parser


def research_date(value: str):
    try:
        return parse_date(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Use a valid research date in YYYY-MM-DD format.") from exc


def inspect_documents(args) -> int:
    folder = args.docs.expanduser().resolve()
    try:
        output_path = args.output.expanduser().resolve() if args.output else None
        if output_path and output_path.is_relative_to(folder):
            raise DocumentError(
                "Save the manifest outside the source directory to preserve inputs."
            )
        eligible, future = load_documents(folder, args.as_of)
        manifest = build_manifest(eligible, future, args.as_of)
        serialized = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
        if output_path:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(serialized, encoding="utf-8")
    except (DocumentError, OSError) as exc:
        print(f"ERROR  {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(serialized, end="")
    else:
        print(f"Research date: {args.as_of.isoformat()}")
        print(f"Eligible: {len(eligible)}; excluded as future: {len(future)}")
        print("\nSource IDs follow filename order and are assigned before date filtering.")
        for source in manifest["sources"]:
            print(
                f"\n{source['source_id']}  {source['status']}  "
                f"{source['published']}  {source['filename']}"
            )
            print(f"  Source: {source['source']}")
            print(f"  Type: {source['source_type']}")
            print(f"  URL: {source['url']}")
            print(f"  Size: {source['size_bytes']} bytes; SHA-256: {source['sha256']}")
        print(
            "\nDate eligibility does not establish relevance or reliability. No API call was made."
        )
    if output_path:
        print(f"Manifest saved: {output_path}", file=sys.stderr if args.json else sys.stdout)
    if not eligible:
        print("ERROR  No sources are eligible on the research date.", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "inspect":
        return inspect_documents(args)
    if args.command == "run":
        from .workflow import WorkflowFailure, run_research

        project_dir = args.project_dir.expanduser().resolve()
        try:
            result = run_research(
                load_settings(project_dir),
                ticker=args.ticker,
                company=args.company,
                docs_dir=args.docs.expanduser().resolve(),
                as_of=args.as_of,
                output_root=(
                    args.output_root.expanduser().resolve()
                    if args.output_root
                    else project_dir / "artifacts" / "runs"
                ),
                writer_version=args.writer_version,
                export_dir=args.export_dir.expanduser().resolve() if args.export_dir else None,
                evidence_run=args.evidence_run.expanduser().resolve()
                if args.evidence_run
                else None,
            )
        except WorkflowFailure as exc:
            print(f"ERROR  {exc}\nRun evidence: {exc.run_dir}", file=sys.stderr)
            return 1
        except (ConfigurationError, DocumentError, OSError) as exc:
            print(f"ERROR  {exc}", file=sys.stderr)
            return 1
        print(f"PASS  Research brief: {result.directory / 'brief.md'}")
        return 0
    if args.command == "extract":
        from .evidence import ExtractionFailure, extract_evidence

        project_dir = args.project_dir.expanduser().resolve()
        output_root = (
            args.output_root.expanduser().resolve()
            if args.output_root
            else project_dir / "artifacts" / "evidence"
        )
        try:
            settings = load_settings(project_dir)
            print(f"Assessing {args.ticker.upper()} sources with {settings.model}...", flush=True)
            result = extract_evidence(
                settings,
                ticker=args.ticker,
                company=args.company,
                docs_dir=args.docs.expanduser().resolve(),
                as_of=args.as_of,
                output_root=output_root,
            )
        except ExtractionFailure as exc:
            print(f"ERROR  {exc}\nRun evidence: {exc.run_dir}", file=sys.stderr)
            return 1
        except (ConfigurationError, DocumentError, OSError) as exc:
            print(f"ERROR  {exc}", file=sys.stderr)
            return 1
        print(
            f"PASS  {len(result.ledger.source_decisions)} source decisions; "
            f"{len(result.ledger.facts)} facts; {len(result.ledger.conflicts)} conflicts/updates"
        )
        print("Every evidence excerpt matches its cited source. Claim meaning still needs review.")
        print(
            f"Elapsed: {result.receipt.elapsed_seconds:.3f}s; "
            f"HTTP attempts: {result.receipt.attempts}; tokens: {result.receipt.total_tokens}"
        )
        print(f"Evidence review: {result.directory / 'review.md'}")
        print(f"Evidence JSON: {result.directory / 'ledger.json'}")
        return 0
    if args.command == "check":
        checks = check_setup(args.project_dir.expanduser().resolve())
        for check in checks:
            print(f"{'PASS' if check.passed else 'FAIL'}  {check.name}: {check.detail}")
        if all(check.passed for check in checks):
            print("\nLocal setup is ready. This command does not test API connectivity.")
            return 0
        print("\nSetup needs attention. See the failed checks above.")
        return 1
    if args.command in {"config", "test-api"}:
        project_dir = args.project_dir.expanduser().resolve()
        try:
            settings = load_settings(project_dir, require_key=args.command == "test-api")
        except ConfigurationError as exc:
            print(f"ERROR  {exc}", file=sys.stderr)
            return 1
        if args.command == "config":
            print("Provider: Google Gemini Developer API")
            print(f"Model: {settings.model}")
            print(f"API key: {'configured' if settings.api_key else 'missing'}")
            print(f"Key source: {settings.key_source}")
            print("API connectivity and billing tier: not checked by this command")
            return 0 if settings.api_key else 1

        from .gemini import GeminiRequestError, check_connection, save_receipt

        print(f"Testing {settings.model}...", flush=True)
        try:
            receipt = check_connection(settings)
        except GeminiRequestError as exc:
            print(f"ERROR  {exc}", file=sys.stderr)
            return 1
        print(f"PASS  {receipt.model}: {receipt.response}")
        print(f"Elapsed: {receipt.elapsed_seconds:.3f}s; attempts: {receipt.attempts}")
        total_tokens = receipt.total_tokens if receipt.total_tokens is not None else "unknown"
        print(f"Total tokens: {total_tokens}")
        try:
            path = save_receipt(receipt, project_dir)
        except OSError:
            print(
                "ERROR  API test passed, but the local receipt could not be saved.", file=sys.stderr
            )
            return 1
        print(f"Receipt: {path}")
        print("The account billing tier and future quota availability were not verified.")
        return 0
    return 2
