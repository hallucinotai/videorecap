import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.enrichment.base import EnrichmentContext
from modules.enrichment.composite import SublayerSkipped
from modules.enrichment.l1_normalize.enricher import L1NormalizeEnricher
from modules.enrichment.l2_identity.sublayers.s1_video_reconcile import S1VideoReconcileEnricher
from tests.fixtures.enrichment_samples import SAMPLE_ASSEMBLYAI


@patch("modules.enrichment.l2_identity.sublayers.s1_video_reconcile.find_speaking_face")
@patch("modules.enrichment.l2_identity.sublayers.s1_video_reconcile.VideoFrameReader")
def test_s1_av_reconcile_uses_lip_samples(mock_reader_cls, mock_find_speaking, tmp_path):
    video_path = tmp_path / "clip.mp4"
    video_path.write_bytes(b"fake")
    mock_reader_cls.return_value = MagicMock()

    base = np.ones(32, dtype=np.float32)
    base /= np.linalg.norm(base)
    crop = np.zeros((80, 80, 3), dtype=np.uint8)

    mock_find_speaking.return_value = MagicMock(
        detection_confidence=0.9,
        lip_motion_score=10.0,
        mouth_openness=1.2,
        embedding=base,
        crop=crop,
        face_index=0,
        bbox=(0, 0, 80, 80),
    )

    ctx = EnrichmentContext(
        job_id="job_vid",
        working_dir=str(tmp_path),
        video_path=str(video_path),
        assets_dir=str(tmp_path / "assets"),
    )
    l1 = L1NormalizeEnricher().enrich(SAMPLE_ASSEMBLYAI, ctx)
    ctx.raw_speakers = SAMPLE_ASSEMBLYAI["speakers"]

    with patch("cv2.imwrite", return_value=True):
        result = S1VideoReconcileEnricher().enrich(l1, ctx)

    assert result["L2_reconciliation"]["method"] == "audiovisual_lip_cluster_v2"
    assert result["L2_reconciliation"]["faces_sampled"] >= 1
    assert mock_find_speaking.call_count >= 1


def test_s1_skips_without_video(tmp_path):
    ctx = EnrichmentContext(
        job_id="j1",
        working_dir=str(tmp_path),
        assets_dir=str(tmp_path / "assets"),
    )
    l1 = L1NormalizeEnricher().enrich(SAMPLE_ASSEMBLYAI, ctx)
    with pytest.raises(SublayerSkipped, match="no_video"):
        S1VideoReconcileEnricher().enrich(l1, ctx)
