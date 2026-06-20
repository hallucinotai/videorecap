"""
Step-by-step storage manager for MinIO.

Organizes pipeline outputs into step-specific directories with metadata and logs.
Enables debugging, quality control, and selective reprocessing of pipeline steps.
"""

import json
import logging
import os
from datetime import datetime

logger = logging.getLogger(__name__)


class StepStorage:
    """Manages step-by-step outputs in MinIO with organized directory structure."""

    STEPS = {
        1: "transcription",
        2: "translation",
        3: "recap_generation",
        4: "tts_generation",
        5: "video_extraction",
        6: "audio_removal",
        7: "final_merge",
    }

    def __init__(self, job_id: str, storage_service):
        """
        Initialize step storage.

        Args:
            job_id: Job identifier
            storage_service: S3/MinIO storage service (with upload_file, upload_bytes methods)
        """
        self.job_id = job_id
        self.storage = storage_service

    def upload_step_output(
        self,
        step_num: int,
        files_dict: dict[str, str],
        metadata: dict = None,
    ) -> dict:
        """
        Upload all outputs for a step.

        Args:
            step_num: Step number (1-7)
            files_dict: {"file_type": "local_path", ...}
            metadata: Optional metadata dict (will be JSON-encoded)

        Returns:
            {"step_XX.file_type": "s3_key", ...} for storage in intermediate_keys
        """
        step_name = self.STEPS.get(step_num, f"step_{step_num}")
        s3_keys = {}
        step_prefix = f"jobs/{self.job_id}/step_{step_num:02d}_{step_name}"

        # Upload each file
        for file_type, local_path in files_dict.items():
            if not os.path.exists(local_path):
                logger.warning(f"Step {step_num}: File not found at {local_path}, skipping")
                continue

            basename = os.path.basename(local_path)
            s3_key = f"{step_prefix}/{basename}"
            with open(local_path, "rb") as f:
                self.storage.upload_file(s3_key, f)
            s3_keys[f"step_{step_num:02d}.{file_type}"] = s3_key
            logger.debug(f"Step {step_num}: Uploaded {file_type} → {s3_key}")

        # Upload metadata
        if metadata:
            metadata_key = f"{step_prefix}/metadata.json"
            self.storage.upload_bytes(
                metadata_key,
                json.dumps(metadata, default=str).encode(),
                "application/json",
            )
            s3_keys[f"step_{step_num:02d}.metadata"] = metadata_key
            logger.debug(f"Step {step_num}: Uploaded metadata → {metadata_key}")

        return s3_keys

    def upload_step_log(self, step_num: int, log_content: str) -> str:
        """
        Upload step execution log.

        Args:
            step_num: Step number
            log_content: Log text

        Returns:
            S3 key of uploaded log
        """
        step_name = self.STEPS.get(step_num, f"step_{step_num}")
        log_key = f"jobs/{self.job_id}/step_{step_num:02d}_{step_name}/log.txt"
        self.storage.upload_bytes(log_key, log_content.encode(), "text/plain")
        logger.debug(f"Step {step_num}: Uploaded log → {log_key}")
        return log_key
