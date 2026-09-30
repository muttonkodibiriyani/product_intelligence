"""PostgreSQL fact store schema (blueprint §5) and its Alembic migrations.

The schema targets PostgreSQL 16 + pgvector: the local Docker stack and, in the cloud,
Cloud SQL behind Firebase Data Connect (ADR-0002). Migrations avoid superuser-only
features so they run unchanged as the Cloud SQL ``cloudsqlsuperuser``-member owner.
"""

import os
from pathlib import Path

from alembic.config import Config

IMAGE_EMBEDDING_DIM = 768
"""SigLIP ViT-B/16 image embedding size (``image.embedding``)."""

TEXT_EMBEDDING_DIM = 1024
"""BGE-M3 dense text embedding size (``variant.text_embedding``)."""

APP_ROLE = "pi_app"
"""Role the application connects as. Observations are INSERT/SELECT only for it."""

DATABASE_URL_ENV = "PI_DATABASE_URL"
MIGRATIONS_DIR = Path(__file__).parent / "migrations"


class DatabaseUrlMissingError(RuntimeError):
    """Raised when no database URL is configured."""


def database_url() -> str:
    """SQLAlchemy URL of the target database, from ``PI_DATABASE_URL``."""
    url = os.environ.get(DATABASE_URL_ENV)
    if not url:
        raise DatabaseUrlMissingError(
            f"{DATABASE_URL_ENV} is not set; copy .env.example to .env or export it"
        )
    return url


def alembic_config(url: str | None = None) -> Config:
    """Alembic config for this package's migrations, usable without an ini file."""
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    if url is not None:
        config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return config


__all__ = [
    "APP_ROLE",
    "DATABASE_URL_ENV",
    "IMAGE_EMBEDDING_DIM",
    "MIGRATIONS_DIR",
    "TEXT_EMBEDDING_DIM",
    "DatabaseUrlMissingError",
    "alembic_config",
    "database_url",
]
