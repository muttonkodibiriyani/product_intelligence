"""Service settings, from the environment (deploy config, never code). Holds no secrets."""

from __future__ import annotations

import re
from collections.abc import Mapping

from pydantic import Field

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


class Settings(PiModel):
    #: Firebase project id: the token ``aud`` and the issuer suffix.
    project_id: str = Field(min_length=1)
    #: Dataset objects to serve, e.g. ``datasets/uae/latest.json`` (gzip content is detected).
    datasets: tuple[str, ...] = Field(min_length=1)
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

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> Settings:
        datasets = tuple(d.strip() for d in env.get("PI_API_DATASETS", "").split(",") if d.strip())
        for path in datasets:
            if not _OBJECT.match(path) or ".." in path:
                msg = f"PI_API_DATASETS entry {path!r} is not a plain .json object path"
                raise ValueError(msg)
        bucket = env.get("PI_API_BUCKET") or None
        local_dir = env.get("PI_API_LOCAL_DIR") or None
        if (bucket is None) == (local_dir is None):
            msg = "set exactly one of PI_API_BUCKET and PI_API_LOCAL_DIR"
            raise ValueError(msg)
        return cls(
            project_id=env.get("PI_API_FIREBASE_PROJECT", ""),
            datasets=datasets,
            bucket=bucket,
            local_dir=local_dir,
            refresh_seconds=int(env.get("PI_API_REFRESH_SECONDS", "60")),
            rate_per_second=int(env.get("PI_API_RATE_PER_SECOND", "10")),
            rate_burst=int(env.get("PI_API_RATE_BURST", "30")),
            allow_test=env.get("PI_API_ALLOW_TEST", "") == "1",
            evidence_hosts=evidence_hosts(env.get("PI_API_EVIDENCE_HOSTS", "")),
            image_hosts=evidence_hosts(env.get("PI_API_IMAGE_HOSTS", ""), "PI_API_IMAGE_HOSTS"),
        )
