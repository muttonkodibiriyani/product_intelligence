"""Regenerate ``pi_capture/_attributes.py`` from ``spec/requirements_v2_attributes.json``.

    uv run python packages/pi_capture/scripts/gen_registry.py

Run it after mirroring a new requirements version into the spec file, then commit both files.
"""

from __future__ import annotations

import sys

from pi_capture.registry_gen import write


def main() -> int:
    target = write()
    sys.stdout.write(f"wrote {target}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
