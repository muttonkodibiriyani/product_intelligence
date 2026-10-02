"""Config, the snapshot source and the certificate cache, without the HTTP layer."""

from __future__ import annotations

import gc
import gzip
import os
import time
import weakref
from pathlib import Path

import httpx
import pytest

from api_fixture import DATASET_PATH, served_dataset, write
from pi_api.app import app_from_env, store_for
from pi_api.auth import CertificatesUnavailableError, HttpCertSource
from pi_api.config import Settings
from pi_api.source import (
    AmbiguousDatasetError,
    DataUnavailableError,
    LocalStore,
    NotFoundError,
    SnapshotSource,
    parse,
)
from pi_dataset import dump_dataset
from pi_metrics.view import as_v3

ENV = {
    "PI_API_FIREBASE_PROJECT": "p",
    "PI_API_DATASETS": " datasets/uae/latest.json , datasets/ksa/latest.json",
    "PI_API_LOCAL_DIR": "/data",
}


def test_settings_from_env() -> None:
    settings = Settings.from_env(ENV)
    assert settings.datasets == ("datasets/uae/latest.json", "datasets/ksa/latest.json")
    assert (settings.refresh_seconds, settings.rate_per_second, settings.rate_burst) == (60, 10, 30)
    assert settings.allow_test is False
    assert Settings.from_env({**ENV, "PI_API_ALLOW_TEST": "1"}).allow_test is True
    assert settings.evidence_hosts == {}
    hosts = " shop_a=shop-a.example, shop_b=b.example ,shop_a=www.shop-a.example,"
    assert Settings.from_env({**ENV, "PI_API_EVIDENCE_HOSTS": hosts}).evidence_hosts == {
        "shop_a": frozenset({"shop-a.example", "www.shop-a.example"}),
        "shop_b": frozenset({"b.example"}),
    }


@pytest.mark.parametrize(
    "env",
    [
        {**ENV, "PI_API_DATASETS": "../secrets.json"},
        {**ENV, "PI_API_DATASETS": "datasets/uae/latest.csv"},
        {**ENV, "PI_API_DATASETS": "a/../b.json"},
        {**ENV, "PI_API_DATASETS": ""},
        {**ENV, "PI_API_BUCKET": "b"},
        {k: v for k, v in ENV.items() if k != "PI_API_LOCAL_DIR"},
        {**ENV, "PI_API_FIREBASE_PROJECT": ""},
        {**ENV, "PI_API_RATE_BURST": "0"},
        {**ENV, "PI_API_EVIDENCE_HOSTS": "shop-a.example"},
        {**ENV, "PI_API_EVIDENCE_HOSTS": "shop_a=https://shop-a.example"},
        {**ENV, "PI_API_EVIDENCE_HOSTS": "shop_a=*.shop-a.example"},
        {**ENV, "PI_API_EVIDENCE_HOSTS": "shop_a=shop-a.example:443"},
        {**ENV, "PI_API_EVIDENCE_HOSTS": "shop_a=Shop-A.example"},
        {**ENV, "PI_API_EVIDENCE_HOSTS": "Shop A=shop-a.example"},
        {**ENV, "PI_API_EVIDENCE_HOSTS": "shop_a=localhost"},
    ],
)
def test_bad_settings_are_refused(env: dict[str, str]) -> None:
    with pytest.raises(ValueError, match=r"."):
        Settings.from_env(env)


def test_app_from_env_loads_before_serving(tmp_path: Path) -> None:
    write(tmp_path, served_dataset())
    env = {**ENV, "PI_API_DATASETS": DATASET_PATH, "PI_API_LOCAL_DIR": str(tmp_path)}
    assert app_from_env(env) is not None
    assert isinstance(store_for(Settings.from_env(env)), LocalStore)


def test_parse_bounds_decompressed_size() -> None:
    raw = dump_dataset(served_dataset())
    assert parse(gzip.compress(raw)).meta.scope == "fixture"
    with pytest.raises(ValueError, match="decompressed"):
        parse(gzip.compress(raw), limit=len(raw) - 1)
    with pytest.raises(ValueError, match="larger"):
        parse(raw, limit=len(raw) - 1)


def test_select_rules(tmp_path: Path) -> None:
    source = SnapshotSource(LocalStore(tmp_path), (DATASET_PATH,))
    with pytest.raises(DataUnavailableError):
        source.select(None, None)
    write(tmp_path, served_dataset())
    source.load_all()
    assert source.select("ae", "fixture").scope == "fixture"
    with pytest.raises(NotFoundError):
        source.select("SA", None)
    assert AmbiguousDatasetError.__mro__[1] is ValueError


def test_maybe_refresh_loads_in_the_background_once_due(tmp_path: Path) -> None:
    now = [0.0]
    source = SnapshotSource(LocalStore(tmp_path), (DATASET_PATH,), 60, clock=lambda: now[0])
    write(tmp_path, served_dataset())
    source.maybe_refresh()
    deadline = time.monotonic() + 10
    while not source.datasets() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert [d.scope for d in source.datasets()] == ["fixture"]
    (tmp_path / DATASET_PATH).unlink()
    now[0] = 30  # not due yet: nothing runs, nothing is dropped
    source.maybe_refresh()
    assert source.datasets()


def test_a_missing_file_is_logged_not_raised(tmp_path: Path) -> None:
    source = SnapshotSource(LocalStore(tmp_path), ("datasets/none.json",))
    source.load_all()
    assert source.datasets() == ()


def test_a_v2_dataset_metrics_cannot_read_is_not_loaded(tmp_path: Path) -> None:
    ds = served_dataset()
    write(tmp_path, ds.model_copy(update={"meta": ds.meta.model_copy(update={"vertical": "toys"})}))
    source = SnapshotSource(LocalStore(tmp_path), (DATASET_PATH,))
    source.load_all()  # no committed toys@1 profile to upgrade it by
    assert source.datasets() == ()


def test_a_replaced_generation_and_its_upgrade_are_freed(tmp_path: Path) -> None:
    write(tmp_path, served_dataset())
    source = SnapshotSource(LocalStore(tmp_path), (DATASET_PATH,))
    source.load_all()
    first = weakref.ref(source.datasets()[0].dataset)
    upgraded = weakref.ref(as_v3(source.datasets()[0].dataset))
    write(tmp_path, served_dataset())
    os.utime(tmp_path / DATASET_PATH, ns=(1, 1))  # a new generation, whatever the clock
    source.load_all()
    gc.collect()
    assert source.datasets()
    assert first() is None
    assert upgraded() is None


def test_a_storage_error_keeps_what_is_loaded(tmp_path: Path) -> None:
    class Flaky(LocalStore):
        fail = False

        def generation(self, path: str) -> str:
            if self.fail:
                raise RuntimeError("storage outage")
            return super().generation(path)

    write(tmp_path, served_dataset())
    store = Flaky(tmp_path)
    source = SnapshotSource(store, (DATASET_PATH,))
    source.load_all()
    store.fail = True
    source.load_all()
    assert source.datasets()


def certs_client(responses: list[httpx.Response]) -> tuple[httpx.Client, list[int]]:
    calls: list[int] = []

    def handler(_: httpx.Request) -> httpx.Response:
        calls.append(1)
        return responses.pop(0)

    return httpx.Client(transport=httpx.MockTransport(handler)), calls


def test_certificates_are_cached_for_max_age() -> None:
    doc = {"k1": "-----BEGIN CERTIFICATE-----"}
    ok = httpx.Response(200, json=doc, headers={"cache-control": "public, max-age=120"})
    client, calls = certs_client([ok, httpx.Response(200, json={"k2": "x"})])
    now = [0.0]
    source = HttpCertSource("https://certs.invalid/", clock=lambda: now[0], client=client)
    assert source.certificates() == doc
    now[0] = 119
    assert source.certificates() == doc
    assert len(calls) == 1
    now[0] = 120
    assert source.certificates() == {"k2": "x"}


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(500),
        httpx.Response(200, content=b"not json"),
        httpx.Response(200, json=["x"]),
        httpx.Response(200, json={"k": 1}),
        httpx.Response(200, json={}),
    ],
)
def test_a_bad_first_certificate_document_fails_closed(response: httpx.Response) -> None:
    client, _ = certs_client([response])
    source = HttpCertSource("https://certs.invalid/", client=client)
    with pytest.raises(CertificatesUnavailableError):
        source.certificates()


def test_failed_refreshes_back_off_and_serve_the_last_good_set_within_grace() -> None:
    doc = {"k1": "pem"}
    ok = httpx.Response(200, json=doc, headers={"cache-control": "max-age=100"})
    down = [httpx.Response(503) for _ in range(20)]
    client, calls = certs_client([ok, *down, httpx.Response(200, json={"k2": "pem"})])
    now = [0.0]
    source = HttpCertSource("https://certs.invalid/", clock=lambda: now[0], client=client)
    assert source.certificates() == doc
    now[0] = 100.0  # expired: one refresh attempt fails, the last good set is still served
    for _ in range(6):
        assert source.certificates() == doc
    assert len(calls) == 2  # no refetch on every request while backing off
    now[0] = 100.9
    assert source.certificates() == doc
    assert len(calls) == 2
    now[0] = 101.0  # backoff 1s elapsed: second attempt, then 2s
    assert source.certificates() == doc
    assert len(calls) == 3
    now[0] = 102.5
    source.certificates()
    assert len(calls) == 3
    now[0] = 103.0
    source.certificates()
    assert len(calls) == 4
    now[0] = 100.0 + HttpCertSource.GRACE  # past the grace: a failed attempt fails closed
    with pytest.raises(CertificatesUnavailableError):
        source.certificates()
    now[0] += HttpCertSource.BACKOFF_MAX
    calls.clear()
    with pytest.raises(CertificatesUnavailableError):
        source.certificates()
    assert len(calls) == 1


def test_backoff_is_capped_and_resets_after_a_good_refresh() -> None:
    down = [httpx.Response(500) for _ in range(10)]
    client, calls = certs_client([*down, httpx.Response(200, json={"k": "pem"})])
    now = [0.0]
    source = HttpCertSource("https://certs.invalid/", clock=lambda: now[0], client=client)
    for _ in range(10):  # backoffs 1, 2, 4, ..., capped at BACKOFF_MAX
        with pytest.raises(CertificatesUnavailableError):
            source.certificates()
        now[0] += HttpCertSource.BACKOFF_MAX
    assert len(calls) == 10
    assert source.certificates() == {"k": "pem"}


class BusyLock:
    """A lock another thread holds: try-acquire fails, a blocking acquire waits (here: returns)."""

    def __init__(self) -> None:
        self.waited = 0

    def acquire(self, blocking: bool = True) -> bool:
        if blocking:
            self.waited += 1
        return blocking

    def release(self) -> None:
        pass


def test_a_refresh_in_flight_serves_the_last_good_set_without_waiting() -> None:
    ok = httpx.Response(200, json={"k": "pem"}, headers={"cache-control": "max-age=10"})
    client, calls = certs_client([ok, httpx.Response(200, json={"k2": "pem"})])
    now = [0.0]
    source = HttpCertSource("https://certs.invalid/", clock=lambda: now[0], client=client)
    source.certificates()
    assert not source.stale()
    busy = BusyLock()
    source._lock = busy  # type: ignore[assignment]
    now[0] = 20.0
    assert source.stale()
    assert source.certificates() == {"k": "pem"}
    assert (busy.waited, len(calls)) == (0, 1)
    now[0] = 10.0 + HttpCertSource.GRACE  # nothing usable: wait for the lock, then refresh
    assert source.certificates() == {"k2": "pem"}
    assert (busy.waited, len(calls)) == (1, 2)
