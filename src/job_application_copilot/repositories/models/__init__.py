"""Registered SQLAlchemy persistence models."""

from job_application_copilot.repositories.models.job import Job
from job_application_copilot.repositories.models.reference_asset import ReferenceAsset

__all__ = ["Job", "ReferenceAsset"]
