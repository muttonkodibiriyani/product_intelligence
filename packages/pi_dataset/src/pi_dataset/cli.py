"""``pi-dataset validate FILE...``, ``schema`` and ``examples DIR``: for publishers and CI."""

from __future__ import annotations

import argparse
import gzip
import sys
from collections.abc import Sequence
from pathlib import Path

from pi_dataset.examples import write_examples
from pi_dataset.validate import DatasetError, load_any, load_dataset, schema_text


def _read(path: Path) -> bytes:
    data = path.read_bytes()
    return gzip.decompress(data) if data[:2] == b"\x1f\x8b" else data


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pi-dataset", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("validate", help="validate pi.dataset/v2 documents (.json or .json.gz)")
    check.add_argument("files", nargs="+", type=Path)
    check.add_argument("--allow-test", action="store_true", help="accept meta.test documents")
    check.add_argument("--v3", action="store_true", help="also accept pi.dataset/v3 documents")
    schema = sub.add_parser("schema", help="print the JSON Schema")
    schema.add_argument("--v3", action="store_true", help="the pi.dataset/v3 schema")
    ex = sub.add_parser("examples", help="write the synthetic example documents")
    ex.add_argument("directory", type=Path)
    args = parser.parse_args(argv)

    if args.command == "schema":
        sys.stdout.write(schema_text(3 if args.v3 else 2))
        return 0
    if args.command == "examples":
        for path in write_examples(args.directory):
            print(path)
        return 0
    failed = 0
    for path in args.files:
        try:
            load = load_any if args.v3 else load_dataset
            dataset = load(_read(path), allow_test=args.allow_test)
        except (DatasetError, OSError) as exc:
            failed += 1
            problems = exc.errors if isinstance(exc, DatasetError) else (str(exc),)
            print(f"{path}: INVALID", file=sys.stderr)
            for problem in problems:
                print(f"  - {problem}", file=sys.stderr)
        else:
            meta = dataset.meta
            markets = ",".join(m.country for m in meta.markets)
            print(f"{path}: ok ({markets}/{meta.scope}, {len(dataset.products)} products)")
    return 1 if failed else 0
