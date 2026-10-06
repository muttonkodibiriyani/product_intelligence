"""Service settings, from the environment (deploy config, never code). Holds no secrets."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Self

from pydantic import Field, model_validator

from pi_core import PiModel

_OBJECT = re.compile(r"^[a-z0-9][a-z0-9_./-]{0,200}\.json$")
_RETAILER = re.compile(r"^[a-z0-9][a-z0-9_]{0,63}$")
_HOST = re.compile(r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")


def evidence_hosts(raw: str, var: str = "PI_API_EVIDENCE_HOSTS") -> dict[str, frozenset[str]]:
    """``retailer=host`` pairs, comma-separated; repeat a retailer for more hosts.

    Exact lower-case host names only: no scheme, port, path or wildcard, so a typo is refused at
    startup instead of opening the allowlist.
    """
    hosts: dict[str, set[str]] = {}
    for pair in (p.strip() for p in raw.split(",")):
        if not pair:
            continue
        retailer, sep, host = (part.strip() for part in pair.partition("="))
        if not sep or not _RETAILER.match(retailer) or not _HOST.match(host):
            msg = f"{var} entry {pair!r} is not retailer=host"
            raise ValueError(msg)
        hosts.setdefault(retailer, set()).add(host)
    return {retailer: frozenset(names) for retailer, names in hosts.items()}


def dataset_entries(raw: str) -> tuple[tuple[str, ...], dict[str, str]]:
    """``PI_API_DATASETS``: comma-separated ``path`` (served whole) or ``source=path`` entries.

    ``source=path`` serves only that source's part of the file (ADR-0010); several sources may
    share a path, and a source is assigned once.
    """
    whole: list[str] = []
    sources: dict[str, str] = {}
    for entry in (e.strip() for e in raw.split(",")):
        if not entry:
            continue
        source, sep, path = (part.strip() for part in entry.rpartition("="))
        if not _OBJECT.match(path) or ".." in path or (sep and not _RETAILER.match(source)):
            msg = f"PI_API_DATASETS entry {entry!r} is not a .json object path or source=path"
            raise ValueError(msg)
        if not sep:
            whole.append(path)
        elif source in sources:
            msg = f"PI_API_DATASETS assigns {source} twice"
            raise ValueError(msg)
        else:
            sources[source] = path
    return tuple(dict.fromkeys(whole)), sources


class Settings(PiModel):
    #: Firebase project id: the token ``aud`` and the issuer suffix.
    project_id: str = Field(min_length=1)
    #: Dataset objects served whole, e.g. ``datasets/uae/latest.json`` (gzip is detected).
    datasets: tuple[str, ...] = ()
    #: Per source (retailer id), the object whose part for that source is served (ADR-0010).
    #: Same-scope sources are composed into one view.
    sources: Mapping[str, str] = Field(default_factory=dict)
    #: ``PI_API_MATCHES``: a ``pi.matches/v1`` file applied to the composed views (ADR-0012 §6).
    matches: str | None = None
    #: Optional SKU identities and galleries; these never change the price dataset's cutoff.
    catalogues: tuple[str, ...] = ()
    #: GCS bucket holding ``datasets``; ``None`` reads them from ``local_dir`` (dev and tests).
    bucket: str | None = None
    local_dir: str | None = None
    #: Seconds between generation checks per instance (design §3).
    refresh_seconds: int = Field(default=60, ge=1)
    #: Per-uid token bucket, per instance (design §4).
    rate_per_second: int = Field(default=10, ge=1)
    rate_burst: int = Field(default=30, ge=1)
    #: Serve ``meta.test`` (synthetic) datasets; off unless a demo deployment opts in.
    allow_test: bool = False
    #: Per retailer, the hosts whose evidence URLs are served; any other URL is sent as null.
    #: Empty (the default) nulls every URL.
    evidence_hosts: Mapping[str, frozenset[str]] = Field(default_factory=dict)
    #: Per retailer, the hosts whose product image URLs are served (same rules); empty nulls all.
    image_hosts: Mapping[str, frozenset[str]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_datasets(self) -> Self:
        if not self.datasets and not self.sources:
            msg = "PI_API_DATASETS names no dataset"
            raise ValueError(msg)
        if self.matches is not None and not self.sources:
            msg = "PI_API_MATCHES applies to per-source views: set source=path in PI_API_DATASETS"
            raise ValueError(msg)
        both = sorted(set(self.datasets) & set(self.sources.values()))
        if both:
            msg = f"PI_API_DATASETS serves {both} both whole and per source"
            raise ValueError(msg)
        return self

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> Settings:
        datasets, sources = dataset_entries(env.get("PI_API_DATASETS", ""))
        catalogues = tuple(
            d.strip() for d in env.get("PI_API_CATALOGUES", "").split(",") if d.strip()
        )
        for path in catalogues:
            if not _OBJECT.match(path) or ".." in path:
                msg = f"dataset/catalogue entry {path!r} is not a plain .json object path"
                raise ValueError(msg)
        matches = env.get("PI_API_MATCHES", "").strip() or None
        if matches is not None and (not _OBJECT.match(matches) or ".." in matches):
            msg = f"PI_API_MATCHES {matches!r} is not a plain .json object path"
            raise ValueError(msg)
        bucket = env.get("PI_API_BUCKET") or None
        local_dir = env.get("PI_API_LOCAL_DIR") or None
        if (bucket is None) == (local_dir is None):
            msg = "set exactly one of PI_API_BUCKET and PI_API_LOCAL_DIR"
            raise ValueError(msg)
        return cls(
            project_id=env.get("PI_API_FIREBASE_PROJECT", ""),
            datasets=datasets,
            sources=sources,
            matches=matches,
            catalogues=catalogues,
            bucket=bucket,
            local_dir=local_dir,
            refresh_seconds=int(env.get("PI_API_REFRESH_SECONDS", "60")),
            rate_per_second=int(env.get("PI_API_RATE_PER_SECOND", "10")),
            rate_burst=int(env.get("PI_API_RATE_BURST", "30")),
            allow_test=env.get("PI_API_ALLOW_TEST", "") == "1",
            evidence_hosts=evidence_hosts(env.get("PI_API_EVIDENCE_HOSTS", "")),
            image_hosts=evidence_hosts(env.get("PI_API_IMAGE_HOSTS", ""), "PI_API_IMAGE_HOSTS"),
        )
