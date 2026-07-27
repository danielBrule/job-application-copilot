"""Tests for the shared remote reference-operation lifecycle."""

from pathlib import Path
from typing import cast
from unittest.mock import Mock

import pytest

from job_application_copilot.config import AppSettings
from job_application_copilot.llm import OpenAIClient, OpenAIConfigurationError
from job_application_copilot.services.remote_reference_operation import (
    remote_reference_operation,
)


class WorkflowError(RuntimeError):
    """Test workflow's safe boundary error."""


@pytest.fixture
def settings(tmp_path: Path) -> AppSettings:
    return AppSettings(_env_file=None, data_dir=tmp_path / "data")


def test_creates_client_lazily_and_closes_it_once(settings: AppSettings) -> None:
    client = Mock(spec=OpenAIClient)
    factory = Mock(return_value=cast(OpenAIClient, client))

    with remote_reference_operation(settings, factory, WorkflowError) as operation:
        factory.assert_not_called()
        assert operation.client is client
        assert operation.client is client

    factory.assert_called_once_with(settings)
    client.close.assert_called_once_with()


def test_does_not_create_client_when_work_finishes_before_remote_access(
    settings: AppSettings,
) -> None:
    factory = Mock()

    with remote_reference_operation(settings, factory, WorkflowError):
        pass

    factory.assert_not_called()


def test_rejects_overlapping_operation_and_releases_after_success(
    settings: AppSettings,
) -> None:
    factory = Mock()

    with remote_reference_operation(settings, factory, WorkflowError):
        with pytest.raises(WorkflowError, match="already running"):
            with remote_reference_operation(settings, factory, WorkflowError):
                pytest.fail("An overlapping operation must not start.")

    with remote_reference_operation(settings, factory, WorkflowError):
        pass


def test_translates_configuration_failure_and_releases_lock(settings: AppSettings) -> None:
    def fail_configuration(_: AppSettings) -> OpenAIClient:
        raise OpenAIConfigurationError("OPENAI_API_KEY is required.")

    with pytest.raises(WorkflowError, match="OPENAI_API_KEY") as captured:
        with remote_reference_operation(
            settings,
            fail_configuration,
            WorkflowError,
        ) as operation:
            _ = operation.client

    assert isinstance(captured.value.__cause__, OpenAIConfigurationError)
    with remote_reference_operation(settings, fail_configuration, WorkflowError):
        pass


def test_closes_client_and_releases_lock_after_workflow_failure(
    settings: AppSettings,
) -> None:
    client = Mock(spec=OpenAIClient)
    factory = Mock(return_value=cast(OpenAIClient, client))

    with pytest.raises(ValueError, match="workflow failed"):
        with remote_reference_operation(settings, factory, WorkflowError) as operation:
            _ = operation.client
            raise ValueError("workflow failed")

    client.close.assert_called_once_with()
    with remote_reference_operation(settings, factory, WorkflowError):
        pass


def test_releases_lock_when_client_close_fails(settings: AppSettings) -> None:
    client = Mock(spec=OpenAIClient)
    client.close.side_effect = RuntimeError("close failed")
    factory = Mock(return_value=cast(OpenAIClient, client))

    with pytest.raises(RuntimeError, match="close failed"):
        with remote_reference_operation(settings, factory, WorkflowError) as operation:
            _ = operation.client

    client.close.assert_called_once_with()
    with remote_reference_operation(settings, Mock(), WorkflowError):
        pass
