from pathlib import Path

import guard_windows
import pytest
from scripts.demo_export.test_withhold import beauty

from pi_dataset import dump_dataset


def write(tmp_path: Path, name: str, body: bytes) -> str:
    path = tmp_path / name
    path.write_bytes(body)
    return f"{name}={path}"


def test_a_withheld_ulta_beside_a_windowed_sephora_stays_quiet(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = guard_windows.main([write(tmp_path, "beauty", dump_dataset(beauty()))])
    out = capsys.readouterr().out
    print(out)
    assert rc == 0
    assert (
        "beauty ulta_ae: window none; since 2026-10-01; whole-retailer ['2026-10-02..2026-10-09']"
        in out
    )
    assert "problems 0" in out
    assert "withheld 1" in out
    assert out.count("window guard: ok") == 1


def test_the_eight_day_gap_without_a_withhold_fires(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = guard_windows.main([write(tmp_path, "beauty", dump_dataset(beauty(None)))])
    out = capsys.readouterr().out
    print(out)
    assert rc == 1
    assert "problems 1" in out
    assert out.count("window gap 8 days in Asia/Dubai") == 1
    assert out.count("window guard: FAIL") == 1


def test_no_bodies_fail(capsys: pytest.CaptureFixture[str]) -> None:
    assert guard_windows.main([]) == 1
    captured = capsys.readouterr()
    assert "bodies 0" in captured.out
    assert captured.err.count("FAIL: no bodies given") == 1


def test_a_malformed_argument_is_refused(capsys: pytest.CaptureFixture[str]) -> None:
    assert guard_windows.main(["beauty.json"]) == 2
    assert capsys.readouterr().err.count("expected KEY=PATH") == 1
