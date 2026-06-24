"""L2.S1: Audiovisual speaker reconciliation — word-chunk sampling + lip motion + face clusters."""

from __future__ import annotations

import logging
import os
from typing import Any

import numpy as np

from modules.enrichment.composite import SublayerSkipped
from modules.enrichment.document import deep_copy_doc
from modules.enrichment.l2_identity.face_analysis import VideoFrameReader, find_speaking_face
from modules.enrichment.l2_identity.reconcile import (
    apply_speaker_merge_to_utterances,
    apply_visual_utterance_corrections,
    assign_speakers_to_clusters,
    build_cluster_to_canonical_speaker,
    build_speaker_merge_map,
    cluster_embeddings,
    face_histogram_embedding,
    merge_raw_speakers,
    resolve_canonical_speaker,
)
from modules.enrichment.l2_identity.sampling import sample_timestamps_for_utterance

logger = logging.getLogger(__name__)


def _dependency_status() -> dict[str, Any]:
    status: dict[str, Any] = {"opencv": False, "mediapipe": False, "errors": {}}
    try:
        import cv2  # noqa: F401

        status["opencv"] = True
    except ImportError as exc:
        status["errors"]["opencv"] = str(exc)
    try:
        import mediapipe as mp  # noqa: F401

        status["mediapipe"] = True
        status["mediapipe_version"] = getattr(mp, "__version__", None)
    except ImportError as exc:
        status["errors"]["mediapipe"] = str(exc)
    return status


def _av_diagnostics(doc: dict[str, Any], ctx: Any, *, skip_reason: str | None = None) -> dict[str, Any]:
    utterances = (doc.get("L1_transcript") or {}).get("utterances") or []
    video_path = getattr(ctx, "video_path", None)
    words_count = sum(len(u.get("words") or []) for u in utterances)
    return {
        "status": "skipped" if skip_reason else "ok",
        "skip_reason": skip_reason,
        "video_path": video_path,
        "video_exists": bool(video_path and os.path.isfile(video_path)),
        "video_size_bytes": os.path.getsize(video_path) if video_path and os.path.isfile(video_path) else None,
        "utterance_count": len(utterances),
        "utterances_with_word_timestamps": sum(1 for u in utterances if u.get("words")),
        "word_timestamp_count": words_count,
        "dependencies": _dependency_status(),
        "hint": _skip_hint(skip_reason),
    }


def _skip_hint(skip_reason: str | None) -> str | None:
    if not skip_reason:
        return None
    if skip_reason == "no_video":
        return "Video path was not passed to enrichment — rebuild worker and re-run the job."
    if skip_reason == "mediapipe_unavailable" or skip_reason == "opencv_unavailable":
        return "Install mediapipe + opencv-python-headless in the Celery worker image, then restart the worker."
    if skip_reason and skip_reason.startswith("no_faces_detected"):
        return "No faces detected at transcript sample times — check dark/low-light footage or lower detection threshold."
    if skip_reason == "video_unreadable":
        return "OpenCV could not decode the video file."
    return "See worker logs for L2.S1 enrichment details."


class S1VideoReconcileEnricher:
    sublayer_id = "S1"

    def on_skip(self, doc: dict[str, Any], ctx: Any, skip_reason: str) -> dict[str, Any]:
        diagnostics = _av_diagnostics(doc, ctx, skip_reason=skip_reason)
        output = deep_copy_doc(doc)
        output["L2_reconciliation"] = {
            "method": "audiovisual_lip_cluster_v2",
            "status": "skipped",
            "skip_reason": skip_reason,
            "diagnostics": diagnostics,
        }
        output["L2_speaker_merge_map"] = {}
        output["L2_video_faces"] = {}
        output["L2_face_clusters"] = {}
        output["L2_av_samples"] = []
        logger.warning("L2.S1 video reconcile skipped: %s | %s", skip_reason, diagnostics.get("hint"))
        return output

    def enrich(self, doc: dict[str, Any], ctx: Any) -> dict[str, Any]:
        deps = _dependency_status()
        if not deps["opencv"]:
            raise SublayerSkipped("opencv_unavailable")
        if not deps["mediapipe"]:
            raise SublayerSkipped("mediapipe_unavailable")

        video_path = getattr(ctx, "video_path", None)
        if not video_path or not os.path.isfile(video_path):
            raise SublayerSkipped("no_video")

        utterances = (doc.get("L1_transcript") or {}).get("utterances") or []
        if not utterances:
            raise SublayerSkipped("no_utterances")

        assets_dir = getattr(ctx, "assets_dir", None)
        if not assets_dir:
            raise SublayerSkipped("no_assets_dir")

        try:
            reader = VideoFrameReader(video_path)
        except Exception as exc:
            raise SublayerSkipped("video_unreadable") from exc

        face_samples: list[dict[str, Any]] = []
        embeddings: list[np.ndarray] = []
        sample_points_total = 0

        try:
            for utterance in utterances:
                aai_speaker = utterance.get("speaker")
                if not aai_speaker:
                    continue
                points = sample_timestamps_for_utterance(utterance)
                sample_points_total += len(points)

                for point in points:
                    ts = float(point["timestamp_sec"])
                    speaking = find_speaking_face(reader, ts, face_histogram_embedding)
                    if not speaking or speaking.embedding is None:
                        continue
                    face_samples.append(
                        {
                            "utterance_id": utterance.get("id"),
                            "aai_speaker": aai_speaker,
                            "timestamp_sec": round(ts, 3),
                            "detection_confidence": round(speaking.detection_confidence, 3),
                            "lip_motion_score": speaking.lip_motion_score,
                            "mouth_openness": speaking.mouth_openness,
                            "sample_method": point.get("method"),
                            "chunk_text": point.get("chunk_text"),
                            "crop": speaking.crop,
                            "embedding": speaking.embedding,
                            "faces_in_frame": speaking.face_index + 1,
                        }
                    )
                    embeddings.append(speaking.embedding)
        finally:
            reader.close()

        if not face_samples:
            raise SublayerSkipped(f"no_faces_detected:{sample_points_total}_sample_points")

        cluster_indices = cluster_embeddings(embeddings)
        for sample, cluster_idx in zip(face_samples, cluster_indices):
            sample["cluster_id"] = cluster_idx

        all_speaker_ids = sorted({u["speaker"] for u in utterances if u.get("speaker")})
        speaker_to_cluster = assign_speakers_to_clusters(face_samples)
        merge_map, clusters_meta = build_speaker_merge_map(all_speaker_ids, speaker_to_cluster)
        cluster_to_canonical = build_cluster_to_canonical_speaker(face_samples)

        # Utterance-level lip-motion corrections (e.g. hallucinated speaker C → B)
        updated_utterances, visual_corrections, visual_relabeled = apply_visual_utterance_corrections(
            utterances,
            face_samples,
            cluster_to_canonical,
        )

        # Speaker-level merge for remaining labels (same face cluster)
        updated_utterances, merge_relabeled = apply_speaker_merge_to_utterances(
            updated_utterances,
            merge_map,
        )
        relabeled = visual_relabeled + merge_relabeled

        merged_raw_speakers = merge_raw_speakers(ctx.raw_speakers or {}, merge_map)
        ctx.raw_speakers = merged_raw_speakers

        diarization_count = len(all_speaker_ids)
        visual_cluster_count = len({s["cluster_id"] for s in face_samples})
        canonical_speaker_ids = sorted({u["speaker"] for u in updated_utterances if u.get("speaker")})

        video_faces: dict[str, Any] = {}
        best_by_cluster: dict[int, dict[str, Any]] = {}
        for sample in face_samples:
            cluster_idx = sample["cluster_id"]
            score = float(sample.get("lip_motion_score") or 0) * float(sample.get("detection_confidence") or 0.5)
            prev = best_by_cluster.get(cluster_idx)
            prev_score = (
                float(prev.get("lip_motion_score") or 0) * float(prev.get("detection_confidence") or 0.5)
                if prev
                else -1
            )
            if prev is None or score > prev_score:
                best_by_cluster[cluster_idx] = sample

        job_id = ctx.job_id
        if not hasattr(ctx, "speaker_asset_paths"):
            ctx.speaker_asset_paths = {}

        import cv2

        for cluster_idx, sample in best_by_cluster.items():
            canonical = cluster_to_canonical.get(cluster_idx)
            if not canonical:
                canonical = resolve_canonical_for_cluster(
                    cluster_idx, speaker_to_cluster, merge_map, all_speaker_ids
                )
            if not canonical:
                continue
            crop = sample["crop"]
            speaker_assets = os.path.join(assets_dir, "speakers", canonical)
            os.makedirs(speaker_assets, exist_ok=True)
            portrait_path = os.path.join(speaker_assets, "portrait.jpg")
            cv2.imwrite(portrait_path, crop)
            portrait_s3_key = f"jobs/{job_id}/assets/speakers/{canonical}/portrait.jpg"
            ctx.speaker_asset_paths[canonical] = portrait_path
            video_faces[canonical] = {
                "cluster_id": f"cluster_{cluster_idx}",
                "visible_ratio": 1.0,
                "alignment_confidence": sample["detection_confidence"],
                "lip_motion_score": sample.get("lip_motion_score"),
                "portrait_local_path": portrait_path,
                "portrait_s3_key": portrait_s3_key,
                "frame_timestamp_sec": sample["timestamp_sec"],
                "utterance_id": sample["utterance_id"],
                "visual_cluster_index": cluster_idx,
            }

        reconciliation = {
            "method": "audiovisual_lip_cluster_v2",
            "status": "ok",
            "diagnostics": _av_diagnostics(doc, ctx),
            "diarization_speaker_count": diarization_count,
            "canonical_speaker_count": len(canonical_speaker_ids),
            "visual_cluster_count": visual_cluster_count,
            "sample_points": sample_points_total,
            "faces_sampled": len(face_samples),
            "speaker_merge_map": merge_map,
            "cluster_to_canonical_speaker": {
                f"cluster_{k}": v for k, v in cluster_to_canonical.items()
            },
            "visual_utterance_corrections": visual_corrections,
            "clusters": clusters_meta,
            "speaker_to_cluster": {
                sid: (f"cluster_{cid}" if cid is not None else None)
                for sid, cid in speaker_to_cluster.items()
            },
            "over_segmentation_corrected": len(merge_map) > 0 or len(visual_corrections) > 0,
            "utterances_relabeled": relabeled,
            "utterances_visual_corrected": visual_relabeled,
            "utterances_merge_corrected": merge_relabeled,
            "mismatch": visual_cluster_count != len(canonical_speaker_ids),
        }

        output = deep_copy_doc(doc)
        l1 = dict(output.get("L1_transcript") or {})
        l1["utterances"] = updated_utterances
        l1["speaker_correction"] = {
            "method": "audiovisual_lip_cluster_v2",
            "merge_map": merge_map,
            "visual_corrections": visual_corrections,
            "original_speaker_count": diarization_count,
            "corrected_speaker_count": len(canonical_speaker_ids),
        }
        output["L1_transcript"] = l1
        output["L2_speaker_merge_map"] = merge_map
        output["L2_video_faces"] = video_faces
        output["L2_reconciliation"] = reconciliation
        output["L2_face_clusters"] = clusters_meta
        output["L2_av_samples"] = _samples_for_debug(face_samples)

        logger.info(
            "L2.S1 av reconcile: %d AAI → %d canonical | %d visual + %d merge relabels | %d samples",
            diarization_count,
            len(canonical_speaker_ids),
            visual_relabeled,
            merge_relabeled,
            len(face_samples),
        )
        return output


def resolve_canonical_for_cluster(
    cluster_idx: int,
    speaker_to_cluster: dict[str, int | None],
    merge_map: dict[str, str],
    all_speaker_ids: list[str],
) -> str | None:
    members = [sid for sid in all_speaker_ids if speaker_to_cluster.get(sid) == cluster_idx]
    if not members:
        return None
    canonical = sorted(members)[0]
    return resolve_canonical_speaker(canonical, merge_map)


def _samples_for_debug(samples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Strip non-JSON-serializable fields (crops, numpy embeddings) from debug samples."""
    skip_keys = {"crop", "embedding"}
    out: list[dict[str, Any]] = []
    for s in samples:
        row: dict[str, Any] = {}
        for k, v in s.items():
            if k in skip_keys:
                continue
            if isinstance(v, np.ndarray):
                continue
            row[k] = v.item() if isinstance(v, np.generic) else v
        out.append(row)
    return out


def s1_artifact(
    doc: dict[str, Any],
    skip_reason: str | None = None,
    ctx: Any | None = None,
) -> dict[str, Any]:
    reconciliation = doc.get("L2_reconciliation") or {}
    if skip_reason and not reconciliation:
        reconciliation = {
            "status": "skipped",
            "skip_reason": skip_reason,
            "diagnostics": _av_diagnostics(doc, ctx or type("C", (), {"video_path": None})(), skip_reason=skip_reason),
        }
    return {
        "status": reconciliation.get("status", "ok" if not skip_reason else "skipped"),
        "skip_reason": skip_reason or reconciliation.get("skip_reason"),
        "diagnostics": reconciliation.get("diagnostics"),
        "L2_reconciliation": reconciliation,
        "L2_speaker_merge_map": doc.get("L2_speaker_merge_map") or {},
        "L2_video_faces": doc.get("L2_video_faces") or {},
        "L2_face_clusters": doc.get("L2_face_clusters") or {},
        "L2_av_samples": doc.get("L2_av_samples") or [],
        "L1_transcript": {
            "speaker_correction": (doc.get("L1_transcript") or {}).get("speaker_correction"),
            "utterance_count": len((doc.get("L1_transcript") or {}).get("utterances") or []),
        },
    }
