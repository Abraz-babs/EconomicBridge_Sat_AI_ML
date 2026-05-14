"""SQLAlchemy declarative base.

A bare DeclarativeBase that all ORM models inherit from. Per-model audit columns
live on each model directly (see models/base_mixin.py) so the registry only carries
the single Base class — keeps inheritance flat for Alembic autogenerate.
"""
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Root declarative base for all SQLAlchemy models in this service."""

    pass
