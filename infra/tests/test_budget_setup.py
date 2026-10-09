"""budget_setup.sh against a fake gcloud on PATH (no network, no billing account)."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

BASH = shutil.which("bash") or "/bin/bash"
SCRIPT = Path(__file__).resolve().parents[1] / "gcp" / "budget_setup.sh"

FAKE_GCLOUD = """#!/bin/bash
printf '%s\\n' "$*" >> "$GCLOUD_LOG"
case "$*" in
  "billing projects describe"*) echo 0000AA-BBBBBB-CCCCCC ;;
  "billing accounts describe"*) echo "$FAKE_CURRENCY" ;;
  "billing budgets list"*--format=value*) printf '%b' "$FAKE_BUDGETS" ;;
esac
"""


def run(tmp_path: Path, currency: str, budgets: str = "") -> tuple[int, list[str]]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gcloud = bin_dir / "gcloud"
    gcloud.write_text(FAKE_GCLOUD)
    gcloud.chmod(0o755)
    log = tmp_path / "gcloud.log"
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "GCLOUD_LOG": str(log),
        "FAKE_CURRENCY": currency,
        "FAKE_BUDGETS": budgets,
    }
    proc = subprocess.run(  # noqa: S603 - fixed script, test-controlled env
        [BASH, str(SCRIPT)], env=env, capture_output=True, text=True, check=False
    )
    calls = log.read_text().splitlines() if log.exists() else []
    return proc.returncode, calls


def writes(calls: list[str]) -> list[str]:
    return [c for c in calls if c.startswith(("billing budgets create", "billing budgets update"))]


def test_creates_the_100usd_budget_with_three_thresholds_when_none_exists(tmp_path: Path) -> None:
    code, calls = run(tmp_path, "USD")
    assert code == 0
    [create] = writes(calls)
    assert create.startswith("billing budgets create --billing-account=0000AA-BBBBBB-CCCCCC")
    assert "--display-name=pi-monthly-100usd --budget-amount=100USD" in create
    assert "--filter-projects=projects/productintelligence-beeb3" in create
    for pct in ("0.5", "0.9", "1.0"):
        assert f"--threshold-rule=percent={pct}" in create


def test_updates_the_old_25usd_budget_in_place_in_aed(tmp_path: Path) -> None:
    name = "billingAccounts/0000AA-BBBBBB-CCCCCC/budgets/abc"
    code, calls = run(tmp_path, "AED", name + "\\n")
    assert code == 0
    [update] = writes(calls)
    assert update.startswith(f"billing budgets update {name} ")
    assert "--display-name=pi-monthly-100usd --budget-amount=367.25AED" in update
    assert "--clear-threshold-rules" in update
    for pct in ("0.5", "0.9", "1.0"):
        assert f"--add-threshold-rule=percent={pct}" in update
    # The notification rule (emails, kill-switch topic) is never rewritten.
    assert "notifications" not in update
    assert "pubsub" not in update


@pytest.mark.parametrize(
    ("currency", "budgets"),
    [("EUR", ""), ("USD", "budgets/a\\nbudgets/b\\n")],
    ids=["unknown-currency", "two-matching-budgets"],
)
def test_refuses_without_writing(tmp_path: Path, currency: str, budgets: str) -> None:
    code, calls = run(tmp_path, currency, budgets)
    assert code == 1
    assert writes(calls) == []
