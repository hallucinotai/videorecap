import json
import os
import tempfile
from unittest.mock import MagicMock, Mock

import pytest

from app.core.step_storage import StepStorage


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def mock_storage():
    """Create a mock storage service."""
    mock = MagicMock()
    mock.upload_file = Mock()
    mock.upload_bytes = Mock()
    return mock


@pytest.fixture
def step_storage(mock_storage):
    """Create a StepStorage instance with mock storage."""
    return StepStorage("test-job-123", mock_storage)


def test_step_storage_initialization(step_storage):
    """Test StepStorage initialization."""
    assert step_storage.job_id == "test-job-123"
    assert step_storage.storage is not None
    assert hasattr(step_storage, "STEPS")
    assert len(step_storage.STEPS) == 7


def test_step_storage_upload_single_file(step_storage, mock_storage, temp_dir):
    """Test uploading a single file for a step."""
    # Create a test file
    test_file = os.path.join(temp_dir, "test_transcript.json")
    with open(test_file, "w") as f:
        json.dump({"text": "test"}, f)

    # Upload
    result = step_storage.upload_step_output(
        step_num=1,
        files_dict={"transcript": test_file},
        metadata={"model": "whisper"},
    )

    # Verify
    assert "step_01.transcript" in result
    assert "step_01.metadata" in result
    mock_storage.upload_file.assert_called_once()
    mock_storage.upload_bytes.assert_called_once()


def test_step_storage_upload_multiple_files(step_storage, mock_storage, temp_dir):
    """Test uploading multiple files for a step."""
    # Create test files
    file1 = os.path.join(temp_dir, "transcript.json")
    file2 = os.path.join(temp_dir, "emotions.json")
    with open(file1, "w") as f:
        json.dump({"text": "test"}, f)
    with open(file2, "w") as f:
        json.dump({"emotion": "happy"}, f)

    # Upload
    result = step_storage.upload_step_output(
        step_num=1,
        files_dict={"transcript": file1, "emotions": file2},
        metadata={"model": "whisper"},
    )

    # Verify
    assert "step_01.transcript" in result
    assert "step_01.emotions" in result
    assert "step_01.metadata" in result
    assert mock_storage.upload_file.call_count == 2
    assert mock_storage.upload_bytes.call_count == 1


def test_step_storage_upload_missing_file(step_storage, mock_storage):
    """Test uploading with a missing file (should skip gracefully)."""
    result = step_storage.upload_step_output(
        step_num=1,
        files_dict={"transcript": "/nonexistent/path/file.json"},
    )

    # Should skip the missing file
    assert "step_01.transcript" not in result
    mock_storage.upload_file.assert_not_called()


def test_step_storage_upload_without_metadata(step_storage, mock_storage, temp_dir):
    """Test uploading without metadata."""
    test_file = os.path.join(temp_dir, "test.json")
    with open(test_file, "w") as f:
        json.dump({"test": "data"}, f)

    result = step_storage.upload_step_output(
        step_num=2,
        files_dict={"transcript": test_file},
        metadata=None,
    )

    # Should only upload the file, not metadata
    assert "step_02.transcript" in result
    assert "step_02.metadata" not in result
    mock_storage.upload_file.assert_called_once()
    mock_storage.upload_bytes.assert_not_called()


def test_step_storage_upload_log(step_storage, mock_storage):
    """Test uploading a step log."""
    log_content = "Step 1 started\nStep 1 completed"

    result = step_storage.upload_step_log(step_num=1, log_content=log_content)

    # Verify
    assert "step_01" in result
    mock_storage.upload_bytes.assert_called_once()
    args, kwargs = mock_storage.upload_bytes.call_args
    assert "log.txt" in args[0]
    assert log_content.encode() == args[1]
    assert kwargs.get("content_type") == "text/plain"


def test_step_storage_all_steps_have_names():
    """Test that all steps have proper names."""
    storage = StepStorage("test", MagicMock())
    for step_num in range(1, 8):
        assert step_num in storage.STEPS
        assert isinstance(storage.STEPS[step_num], str)
        assert len(storage.STEPS[step_num]) > 0


def test_step_storage_key_naming_convention(step_storage, mock_storage, temp_dir):
    """Test that S3 keys follow the proper naming convention."""
    test_file = os.path.join(temp_dir, "data.json")
    with open(test_file, "w") as f:
        json.dump({}, f)

    step_storage.upload_step_output(
        step_num=3,
        files_dict={"transcript": test_file},
    )

    # Get the uploaded S3 key
    args, _ = mock_storage.upload_file.call_args
    s3_key = args[0]

    # Verify naming convention
    assert s3_key.startswith("jobs/test-job-123/step_03_")
    assert "data.json" in s3_key
