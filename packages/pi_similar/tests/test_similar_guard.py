"""The similar signal stays out of every metric and identity path (design §1)."""

import ast
from pathlib import Path

import pytest

PACKAGES = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("package", ["pi_metrics", "pi_api", "pi_match", "pi_dataset", "pi_db"])
def test_no_metric_or_identity_code_imports_pi_similar(package: str) -> None:
    sources = sorted((PACKAGES / package / "src").rglob("*.py"))
    assert sources
    for path in sources:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = (
                [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else []
            )
            assert not any(name.split(".")[0] == "pi_similar" for name in names), path
