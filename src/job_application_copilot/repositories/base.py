"""Shared SQLAlchemy declarative metadata."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for future persisted domain models."""
