from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


MODE_SUFFIX = "-mode.md"
PAGE_MARKER_RE = re.compile(r"\[\[PAGE\s+(\d+)\]\]", re.IGNORECASE)


def discover_mode_files(directory: Path | None = None) -> list[Path]:
    """Return reader instruction files in stable display order."""

    root = (directory or Path(__file__).parent).resolve()
    return sorted(
        (
            path
            for path in root.iterdir()
            if path.is_file()
            and path.name.casefold().endswith(MODE_SUFFIX)
        ),
        key=lambda path: path.name.casefold(),
    )


def describe_mode(path: Path) -> dict[str, str]:
    """Build a compact human-readable mode record from a Markdown file."""

    content = path.read_text(
        encoding="utf-8",
        errors="replace",
    )
    title = ""

    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            title = stripped.lstrip("#").strip()
            break

    return {
        "name": path.name,
        "title": title or path.stem,
    }


def extract_pdf_text(source: Path) -> str:
    """Extract selectable PDF text and preserve page anchors."""

    try:
        from pypdf import PdfReader
    except ImportError as error:
        raise RuntimeError(
            "pypdf is required to read PDF files"
        ) from error

    reader = PdfReader(str(source))
    extracted_pages: list[str] = []

    for page_number, page in enumerate(reader.pages, start=1):
        page_text = page.extract_text() or ""
        extracted_pages.append(
            f"\n[[PAGE {page_number}]]\n{page_text}"
        )

    return "".join(extracted_pages)


def load_source_text(
    source: Path,
    *,
    cache: Path | None = None,
) -> tuple[str, bool]:
    """Load a text-like source once, optionally reusing an extracted cache."""

    if cache is not None and cache.is_file():
        return (
            cache.read_text(
                encoding="utf-8",
                errors="replace",
            ),
            True,
        )

    if not source.is_file():
        raise FileNotFoundError(str(source))

    text = (
        extract_pdf_text(source)
        if source.suffix.casefold() == ".pdf"
        else source.read_text(
            encoding="utf-8",
            errors="replace",
        )
    )

    if cache is not None:
        cache.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        cache.write_text(
            text,
            encoding="utf-8",
        )

    return text, False


def split_words(text: str) -> list[str]:
    """Use a deterministic whitespace contract for offsets and chunk sizes."""

    return re.findall(r"\S+", text)


def read_document_chunk(
    words: list[str],
    offset: int,
    size: int,
) -> dict[str, Any]:
    """Return one ordered chunk and the cursor needed for the next call."""

    safe_offset = max(0, int(offset))
    safe_size = max(1, int(size))
    chunk_words = words[
        safe_offset:safe_offset + safe_size
    ]
    text = " ".join(chunk_words)
    words_read = len(chunk_words)
    next_offset = safe_offset + words_read

    return {
        "offset": safe_offset,
        "size": safe_size,
        "words_read": words_read,
        "next_offset": next_offset,
        "total_words": len(words),
        "eof": next_offset >= len(words),
        "pages_in_chunk": PAGE_MARKER_RE.findall(text),
        "text": text,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "JIN universal chunk reader for text files, Markdown, and PDFs."
        )
    )
    parser.add_argument(
        "--source",
        default="",
        help="Path to the document used by info/read.",
    )
    parser.add_argument(
        "--cache",
        default="",
        help="Optional extracted-text cache used by info/read.",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON for manual tests.",
    )

    commands = parser.add_subparsers(
        dest="command",
        required=True,
    )
    commands.add_parser(
        "modes",
        help=f"List instruction files matching *{MODE_SUFFIX}.",
    )
    commands.add_parser(
        "info",
        help="Return document metadata and available reader modes.",
    )

    read_command = commands.add_parser(
        "read",
        help="Read one deterministic word chunk.",
    )
    read_command.add_argument(
        "offset",
        type=int,
        help="Zero-based word offset.",
    )
    read_command.add_argument(
        "size",
        nargs="?",
        type=int,
        default=2000,
        help="Maximum number of words to return.",
    )

    return parser


def require_source(value: str) -> Path:
    if not str(value or "").strip():
        raise ValueError("--source is required for info and read")

    return Path(value).expanduser().resolve()


def build_result(args: argparse.Namespace) -> dict[str, Any]:
    mode_records = [
        describe_mode(path)
        for path in discover_mode_files()
    ]

    if args.command == "modes":
        return {
            "mode_suffix": MODE_SUFFIX,
            "modes": mode_records,
        }

    source = require_source(args.source)
    cache = (
        Path(args.cache).expanduser().resolve()
        if args.cache
        else None
    )
    text, cache_hit = load_source_text(
        source,
        cache=cache,
    )
    words = split_words(text)

    if args.command == "info":
        return {
            "source": source.name,
            "format": source.suffix.casefold().lstrip(".") or "text",
            "total_words": len(words),
            "pages": len(PAGE_MARKER_RE.findall(text)),
            "cache_hit": cache_hit,
            "modes": mode_records,
        }

    return read_document_chunk(
        words,
        args.offset,
        args.size,
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        result = build_result(args)
        print(
            json.dumps(
                result,
                ensure_ascii=False,
                indent=2 if args.pretty else None,
            )
        )
        return 0
    except Exception as error:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": error.__class__.__name__,
                    "detail": str(error),
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
