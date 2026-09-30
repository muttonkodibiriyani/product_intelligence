"""Fail CI when a JUnit report ran no tests or skipped any.

Used for the real-browser tests: each engine skips itself when it cannot launch, which is
right on a laptop but would hide a broken browser install in CI.

Usage: python .github/scripts/assert_no_skips.py <junit.xml>
"""

import sys
import xml.etree.ElementTree as ET


def main(path: str) -> int:
    # The report is written by our own pytest run a step earlier, not untrusted input.
    cases = ET.parse(path).getroot().iter("testcase")  # noqa: S314
    ran = 0
    skipped: list[str] = []
    for case in cases:
        ran += 1
        skip = case.find("skipped")
        if skip is not None:
            name = f"{case.get('classname')}::{case.get('name')}"
            skipped.append(f"{name} — {skip.get('message', '').strip()}")
    if ran == 0:
        print(f"::error::{path}: no tests collected")
        return 1
    if skipped:
        for line in skipped:
            print(f"::error::skipped: {line}")
        print(f"{len(skipped)} of {ran} tests skipped; expected 0")
        return 1
    print(f"{ran} tests ran, 0 skipped")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
