"""run_env_assert: a Cloud Run describe body's env is present, by name, for each resource kind."""

import json
from pathlib import Path
from typing import Any

import pytest
from run_env_assert import FAIL, MALFORMED, OK, check, main

ENV = [
    {"name": "PI_API_DATASETS", "value": "faces_ae=datasets/ae/faces_ae/latest.json"},
    {"name": "PI_API_BUCKET", "value": "b"},
]


def service(env: list[dict[str, str]] | None) -> dict[str, Any]:
    container: dict[str, Any] = {"image": "x"}
    if env is not None:
        container["env"] = env
    return {
        "kind": "Service",
        "metadata": {"name": "pi-api"},
        "spec": {"template": {"spec": {"containers": [container]}}},
    }


def revision(env: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "kind": "Revision",
        "metadata": {"name": "pi-api-00036-lev"},
        "spec": {"containers": [{"env": env}]},
    }


def job(env: list[dict[str, str]]) -> dict[str, Any]:
    task = {"spec": {"containers": [{"env": env}]}}
    return {
        "kind": "Job",
        "metadata": {"name": "pi-sephora-snapshot"},
        "spec": {"template": {"spec": {"template": task}}},
    }


@pytest.mark.parametrize("body", [service(ENV), revision(ENV), job(ENV)])
def test_quiet_on_every_kind(body: dict[str, Any]) -> None:
    code, lines = check(body, ["PI_API_DATASETS"])
    assert code == OK
    assert lines[1:] == ["  PI_API_DATASETS", "  PI_API_BUCKET", "ENV PRESENT"]


def test_prints_names_never_values() -> None:
    _, lines = check(service(ENV), [])
    assert not any("datasets/ae" in line or line.endswith("b") for line in lines)


@pytest.mark.parametrize("env", [None, []])
def test_empty_env_fails(env: list[dict[str, str]] | None) -> None:
    code, lines = check(service(env), [])
    assert code == FAIL
    assert lines[-1] == "FAIL: env is empty"


def test_missing_required_fails() -> None:
    code, lines = check(service(ENV), ["PI_API_DATASETS", "PI_API_REQUIRE_ALL"])
    assert code == FAIL
    assert lines[-1] == "FAIL: missing required: PI_API_REQUIRE_ALL"


@pytest.mark.parametrize(
    "body",
    [
        [],
        {"kind": "Route"},
        {"kind": "Service", "spec": {}},
        # A job body read at the service depth: the shape this gate exists to catch.
        {"kind": "Job", "spec": {"template": {"spec": {"containers": [{"env": ENV}]}}}},
        {"kind": "Service", "spec": {"template": {"spec": {"containers": []}}}},
        service([{"value": "no name"}]),
    ],
)
def test_unknown_shape_is_malformed(body: Any) -> None:
    code, lines = check(body, [])
    assert code == MALFORMED
    assert len(lines) == 1
    assert lines[0].startswith("MALFORMED: ")


def test_main_exit_codes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    good, bad, empty = tmp_path / "good.json", tmp_path / "bad.json", tmp_path / "empty.json"
    good.write_text(json.dumps(job(ENV)))
    bad.write_text("not json")
    empty.write_text(json.dumps(service([])))
    assert main([str(good), "--require", "PI_API_BUCKET"]) == OK
    assert main([str(empty)]) == FAIL
    assert main([str(bad)]) == MALFORMED
    assert main([str(tmp_path / "absent.json")]) == MALFORMED
    out = capsys.readouterr().out
    assert out.count("ENV PRESENT") == 1
    assert out.count("MALFORMED: cannot read") == 2
