"""CLI: ``python -m offline_import <file> --mapping <cfg> [--dry-run] [--report out.json]``.

``--content-only`` loads a feed re-derived from pages already imported: page content only,
append-only (see ``Loader.load_content``).

The dry run reads and validates only; it never reads PI_DATABASE_URL or opens a connection.
Exit codes: 0 done (rejected rows are listed in the report), 2 unusable mapping or file, or a
content-only load of a feed already imported in full.
"""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

import psycopg
from pydantic import ValidationError
from sqlalchemy.engine import make_url

from offline_import.load import Loader
from offline_import.mapping import load_mapping
from offline_import.readers import FeedError
from offline_import.validate import ImportReport, validate_file
from pi_db import database_url


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="offline_import", description=__doc__.splitlines()[0])
    p.add_argument("file", type=Path, help="feed file: .csv, .xlsx or .json")
    p.add_argument(
        "--mapping", type=Path, required=True, help="column-mapping config (.json/.yaml)"
    )
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="validate only; no database access")
    mode.add_argument(
        "--content-only",
        action="store_true",
        help="append page content for listings already loaded (a re-derived feed); no run,"
        " listing or offer rows",
    )
    p.add_argument("--report", type=Path, help="write the JSON validation report here")
    p.add_argument(
        "--uri",
        help="evidence storage URI of the file (e.g. its gs:// archive copy); default file://",
    )
    return p


def _libpq(url: str) -> str:
    return make_url(url).set(drivername="postgresql").render_as_string(hide_password=False)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        mapping = load_mapping(args.mapping)
        report: ImportReport = validate_file(args.file, mapping)
    except (OSError, ValueError, ValidationError, FeedError) as exc:
        print(f"offline_import: {exc}", file=sys.stderr)
        return 2
    print(report.summary(), file=sys.stderr)
    out = report.to_json()
    if not args.dry_run:
        uri = args.uri or args.file.resolve().as_uri()
        with psycopg.connect(_libpq(database_url())) as conn:
            loader = Loader(conn, mapping, report, uri)
            try:
                out["load"] = loader.load_content() if args.content_only else loader.load()
            except ValueError as exc:
                print(f"offline_import: {exc}", file=sys.stderr)
                return 2
    out["dry_run"] = bool(args.dry_run)
    if args.report:
        args.report.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({k: v for k, v in out.items() if k not in {"rejected", "warnings"}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
