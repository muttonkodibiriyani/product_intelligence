"""Service settings, from the environment (deploy config, never code). Holds no secrets."""

from __future__ import annotations

import re
from collections.abc import Mapping

from pydantic import Field

from pi_core import PiModel

_OBJECT = re.compile(r"^[a-z0-9][a-z0-9_./-]{0,200}\.json$")


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
        )
