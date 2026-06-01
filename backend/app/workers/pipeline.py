import logging
import os
import shutil
import tempfile
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.processing.audio_processing import generate_tts_service, merge_audio_video_service
from app.processing.progress import ProgressReporter
from app.processing.transcription import transcribe_video_service, translate_transcription_service
from app.processing.video_processing import extract_clips_service, generate_recap_service, remove_audio_service
from app.config import settings
from app.services.storage import storage

logger = logging.getLogger(__name__)


class RecapPipeline:
    """Orchestrates the 7-step video recap pipeline with S3 integration."""

    def __init__(self, job_id: str, job_config: dict, input_video_key: str | None,
                 update_job_fn=None, publish_progress_fn=None):
        self.job_id = job_id
        self.config = job_config
        self.input_video_key = input_video_key
        self.update_job_fn = update_job_fn
        self.working_dir = None

        reporter_callback = publish_progress_fn or (lambda **kw: None)
        self.progress = ProgressReporter(reporter_callback)

    def _setup_working_dir(self) -> str:
        working_dir = tempfile.mkdtemp(prefix=f"recap_{self.job_id}_")
        for subdir in [
            "output/transcriptions",
            "output/videos",
            "output/audio",
            "output/original",
            "output/temp",
        ]:
            os.makedirs(os.path.join(working_dir, subdir), exist_ok=True)
        self.working_dir = working_dir
        return working_dir

    def _progress_callback(self, step: int, message: str):
        self.progress.report(step, message, sub_progress=0.5)

    def _update_job(self, **kwargs):
        if self.update_job_fn:
            self.update_job_fn(self.job_id, **kwargs)

    def _upload_intermediate(self, keys_dict: dict, name: str, local_path: str):
        if not os.path.exists(local_path):
            return
        s3_key = f"jobs/{self.job_id}/{name}/{os.path.basename(local_path)}"
        with open(local_path, "rb") as f:
            storage.upload_file(s3_key, f)
        keys_dict[name] = s3_key
        self._update_job(intermediate_keys=dict(keys_dict))

    def _download_intermediate(self, keys_dict: dict, name: str, local_path: str) -> str | None:
        """Download a previously saved intermediate artifact from S3."""
        s3_key = keys_dict.get(name)
        if not s3_key:
            return None
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        storage.download_file(s3_key, local_path)
        logger.info(f"Restored intermediate '{name}' from S3 → {local_path}")
        return local_path

    def run(self, resume_from_step: int = 0, existing_intermediate_keys: dict | None = None):
        working_dir = self._setup_working_dir()
        intermediate_keys = dict(existing_intermediate_keys or {})

        try:
            if not self.input_video_key:
                raise ValueError(
                    "Original upload is no longer in storage and cannot be used to continue processing."
                )

            # Always download input video
            self._update_job(status="processing", current_step=0, current_step_name="Downloading video")
            self.progress.report(0, "Downloading video from storage...", 0.0)
            video_filename = os.path.basename(self.input_video_key)
            local_video_path = os.path.join(working_dir, video_filename)
            storage.download_file(self.input_video_key, local_video_path)

            target_duration = self.config.get("target_duration", 30)
            model_size = self.config.get("whisper_model", "small")
            language = self.config.get("language")
            translate_to = self.config.get("translate_to")
            tts_model = self.config.get("tts_model", "tts-1")
            tts_voice = self.config.get("tts_voice", "nova")
            include_emotions = self.config.get("include_emotions", False)

            # --- Restore intermediates needed for resumption ---
            transcription_file = None
            active_transcription = None
            emotions_file = None
            recap_data_file = None
            recap_text_file = os.path.join(working_dir, "output/transcriptions/recap_text.txt")
            tts_audio_file = None
            actual_audio_duration = None
            recap_video_file = None
            no_audio_video = None

            if resume_from_step >= 2:
                if "translation" in intermediate_keys:
                    active_transcription = self._download_intermediate(
                        intermediate_keys, "translation",
                        os.path.join(working_dir, "output/transcriptions/translated.json"))
                if not active_transcription and "transcription" in intermediate_keys:
                    active_transcription = self._download_intermediate(
                        intermediate_keys, "transcription",
                        os.path.join(working_dir, "output/transcriptions/transcription.json"))
                transcription_file = active_transcription
                # Also restore emotions if they were analyzed
                if include_emotions and "emotions" in intermediate_keys:
                    emotions_file = self._download_intermediate(
                        intermediate_keys, "emotions",
                        os.path.join(working_dir, "output/transcriptions/emotions.json"))

            if resume_from_step >= 4 and "recap_data" in intermediate_keys:
                recap_data_file = self._download_intermediate(
                    intermediate_keys, "recap_data",
                    os.path.join(working_dir, "output/transcriptions/recap_data.json"))
                if recap_data_file:
                    import json as _json
                    with open(recap_data_file) as f:
                        _recap = _json.load(f)
                    with open(recap_text_file, "w") as f:
                        f.write(_recap.get("recap_text", ""))

            if resume_from_step >= 5 and "tts_audio" in intermediate_keys:
                tts_audio_file = self._download_intermediate(
                    intermediate_keys, "tts_audio",
                    os.path.join(working_dir, "output/audio/recap_narration.mp3"))
                if tts_audio_file:
                    from pydub import AudioSegment
                    audio_seg = AudioSegment.from_mp3(tts_audio_file)
                    actual_audio_duration = len(audio_seg) / 1000.0
                    logger.info(f"Restored TTS audio duration: {actual_audio_duration:.1f}s")

            if resume_from_step >= 6 and "recap_video" in intermediate_keys:
                recap_video_file = self._download_intermediate(
                    intermediate_keys, "recap_video",
                    os.path.join(working_dir, "output/videos/recap_video.mp4"))

            if resume_from_step >= 7:
                if recap_video_file:
                    no_audio_video_path = os.path.join(working_dir, "output/videos/recap_video_no_audio.mp4")
                    no_audio_video = no_audio_video_path

            if resume_from_step > 0:
                logger.info(f"Resuming job {self.job_id} from step {resume_from_step}")

            # Step 1: Transcribe (+ emotions if PREMIUM tier)
            emotion_analysis_status = None
            emotion_analysis_error = None
            if resume_from_step <= 1:
                self._update_job(current_step=1, current_step_name="Transcribing video")
                self.progress.report(1, "Starting transcription...", 0.0)
                result = transcribe_video_service(
                    local_video_path, working_dir,
                    model_size=model_size, language=language,
                    include_emotions=include_emotions,
                    progress_callback=self._progress_callback,
                )
                transcription_file = result["transcription_file"]
                emotions_file = result.get("emotions_file")  # None for BASIC tier, path for PREMIUM
                active_transcription = transcription_file
                self._upload_intermediate(intermediate_keys, "transcription", transcription_file)

                # Track emotion analysis status
                if include_emotions:
                    if emotions_file:
                        emotion_analysis_status = "completed"
                        self._upload_intermediate(intermediate_keys, "emotions", emotions_file)
                        logger.info(f"✅ Emotion analysis completed: {emotions_file}")
                    else:
                        emotion_analysis_status = "failed"
                        emotion_analysis_error = "Google Cloud Speech API error. Check logs for details."
                        logger.warning(f"❌ Emotion analysis failed for job {self.job_id}. Continuing with basic transcription.")
                else:
                    emotion_analysis_status = "skipped"

                self._update_job(
                    emotion_analysis_status=emotion_analysis_status,
                    emotion_analysis_error=emotion_analysis_error
                )
                self.progress.report(1, "Transcription complete", 1.0)
            else:
                self.progress.report(1, "Transcription (cached)", 1.0)

            # Step 2: Translate (optional)
            if resume_from_step <= 2:
                if translate_to:
                    self._update_job(current_step=2, current_step_name="Translating")
                    self.progress.report(2, "Starting translation...", 0.0)
                    source_lang = language or "en"
                    result = translate_transcription_service(
                        active_transcription, working_dir,
                        source_lang=source_lang, target_lang=translate_to,
                        progress_callback=self._progress_callback,
                    )
                    active_transcription = result["translated_file"]
                    self._upload_intermediate(intermediate_keys, "translation", active_transcription)
                    self.progress.report(2, "Translation complete", 1.0)
                else:
                    self.progress.report(2, "Translation skipped", 1.0)
            else:
                self.progress.report(2, "Translation (cached)", 1.0)

            # Step 3: Generate recap (with emotion weighting if PREMIUM tier)
            if resume_from_step <= 3:
                self._update_job(current_step=3, current_step_name="Generating recap")
                self.progress.report(3, "Generating recap suggestions...", 0.0)
                narration_lang = translate_to or language or "English"
                result = generate_recap_service(
                    active_transcription, working_dir,
                    target_duration=target_duration,
                    narration_language=narration_lang,
                    emotions_file=emotions_file,  # None for BASIC, path for PREMIUM
                    progress_callback=self._progress_callback,
                )
                recap_data_file = result["recap_data_file"]
                self._upload_intermediate(intermediate_keys, "recap_data", recap_data_file)

                # Log emotion analysis metrics
                import json as _json
                try:
                    with open(recap_data_file) as f:
                        recap_data = _json.load(f)

                    emotions_used = recap_data.get("emotions_used", False)
                    clip_emotions = recap_data.get("clip_emotions", [])

                    if emotions_used:
                        logger.info(f"✓ EMOTION ANALYSIS ENABLED (PREMIUM TIER)")
                        logger.info(f"  Clips selected: {len(recap_data.get('clip_timings', []))}")
                        logger.info(f"  Emotional moments: {len(clip_emotions)}")

                        # Log emotion breakdown
                        emotion_counts = {}
                        for clip_emotion in clip_emotions:
                            emotion = clip_emotion.get("dominant_emotion", "neutral")
                            emotion_counts[emotion] = emotion_counts.get(emotion, 0) + 1

                        logger.info(f"  Emotion distribution: {emotion_counts}")

                        # Log intensity stats
                        intensities = [clip_emotion.get("intensity", 0) for clip_emotion in clip_emotions]
                        if intensities:
                            logger.info(f"  Intensity range: {min(intensities):.2f} - {max(intensities):.2f} (avg: {sum(intensities)/len(intensities):.2f})")
                    else:
                        logger.info(f"✓ BASIC TRANSCRIPTION ONLY (no emotion analysis)")
                        logger.info(f"  Clips selected: {len(recap_data.get('clip_timings', []))}")
                except Exception as e:
                    logger.warning(f"Could not parse recap metrics: {e}")

                self.progress.report(3, "Recap generated", 1.0)
            else:
                self.progress.report(3, "Recap (cached)", 1.0)

            # Step 4: Generate TTS
            if resume_from_step <= 4:
                self._update_job(current_step=4, current_step_name="Generating narration")
                self.progress.report(4, "Generating TTS narration...", 0.0)
                result = generate_tts_service(
                    recap_text_file, working_dir,
                    target_duration=target_duration,
                    tts_model=tts_model, voice=tts_voice,
                    progress_callback=self._progress_callback,
                )
                tts_audio_file = result["tts_audio_file"]
                actual_audio_duration = result["actual_audio_duration"]
                self._upload_intermediate(intermediate_keys, "tts_audio", tts_audio_file)
                if actual_audio_duration < target_duration * 0.6:
                    logger.warning(
                        "TTS audio (%.1fs) is much shorter than target (%ds) — "
                        "narration may have underproduced words",
                        actual_audio_duration, target_duration,
                    )
                self.progress.report(4, f"TTS narration ready ({actual_audio_duration:.1f}s)", 1.0)
            else:
                self.progress.report(4, "TTS narration (cached)", 1.0)

            # Clip/merge duration logic:
            # - Never exceed target + small overshoot (prevents runaway output)
            # - Never shrink below target_duration even if TTS came out short
            #   (better to have extra silent video than to throw away the user's
            #   target because the narration underproduced)
            overshoot = 5
            audio_pad = 1  # extra second so narration audio isn't clipped at the end
            user_trim_cap = target_duration + overshoot
            _ad = actual_audio_duration if actual_audio_duration is not None else float(target_duration)
            clip_trim_target = max(float(target_duration), min(user_trim_cap, _ad + overshoot + audio_pad))

            if resume_from_step <= 5:
                self._update_job(current_step=5, current_step_name="Extracting clips")
                self.progress.report(5, "Extracting video clips...", 0.0)
                result = extract_clips_service(
                    local_video_path, recap_data_file, working_dir,
                    target_duration=clip_trim_target,
                    progress_callback=self._progress_callback,
                )
                recap_video_file = result["recap_video_file"]
                self._upload_intermediate(intermediate_keys, "recap_video", recap_video_file)
                self.progress.report(5, "Clips extracted", 1.0)
            else:
                self.progress.report(5, "Clips (cached)", 1.0)

            # Step 6: Remove audio
            if resume_from_step <= 6:
                self._update_job(current_step=6, current_step_name="Removing audio")
                self.progress.report(6, "Removing original audio...", 0.0)
                result = remove_audio_service(
                    recap_video_file, working_dir,
                    progress_callback=self._progress_callback,
                )
                no_audio_video = result["no_audio_video_file"]
                self.progress.report(6, "Audio removed", 1.0)
            else:
                self.progress.report(6, "Audio removal (cached)", 1.0)

            # Pre-merge timing summary
            try:
                from moviepy.editor import VideoFileClip as _VFC
                _probe = _VFC(no_audio_video)
                merged_clip_duration = _probe.duration
                _probe.close()
            except Exception:
                merged_clip_duration = None

            logger.info(
                "Pre-merge summary for job %s | "
                "TTS audio: %.1fs | Merged clips: %s | "
                "Target: %ds | Clip trim target: %.1fs | Trim cap: %.1fs",
                self.job_id,
                actual_audio_duration or 0,
                f"{merged_clip_duration:.1f}s" if merged_clip_duration else "unknown",
                target_duration,
                clip_trim_target,
                user_trim_cap,
            )
            if settings.DEBUG:
                logger.info(
                    "DEBUG timing detail for job %s | "
                    "audio_longer_than_video=%s | audio_longer_than_target=%s | "
                    "video_longer_than_target=%s",
                    self.job_id,
                    (actual_audio_duration or 0) > (merged_clip_duration or 0),
                    (actual_audio_duration or 0) > target_duration,
                    (merged_clip_duration or 0) > target_duration,
                )

            # Step 7: Merge audio + video
            self._update_job(current_step=7, current_step_name="Merging final video")
            self.progress.report(7, "Merging audio with video...", 0.0)
            result = merge_audio_video_service(
                no_audio_video,
                tts_audio_file,
                working_dir,
                progress_callback=self._progress_callback,
                max_duration_seconds=user_trim_cap,
            )
            final_video = result["final_video_file"]
            self.progress.report(7, "Final video ready", 1.0)

            # Upload final output to S3
            output_key = f"results/{self.job_id}/recap_video_with_narration.mp4"
            with open(final_video, "rb") as f:
                storage.upload_file(output_key, f)

            # Calculate expiry based on tier (default 7 days for free)
            expires_at = datetime.now(timezone.utc) + timedelta(days=7)

            self._update_job(
                status="completed",
                current_step=7,
                current_step_name="Complete",
                progress_pct=100.0,
                output_video_key=output_key,
                intermediate_keys=intermediate_keys,
                completed_at=datetime.now(timezone.utc),
                expires_at=expires_at,
            )

            # Best-effort post-completion cleanup: remove the original upload.
            # This must NEVER revert the successful completion above.
            input_removed = False
            if settings.DELETE_INPUT_VIDEO_ON_COMPLETE and self.input_video_key:
                input_key = self.input_video_key
                try:
                    # DB first: clear the key so no code path references a
                    # file that is about to be deleted.
                    self._update_job(input_video_key=None)
                    storage.delete_file(input_key)
                    self.input_video_key = None
                    input_removed = True
                except Exception:
                    logger.warning(
                        "Post-completion input cleanup failed for job %s",
                        self.job_id, exc_info=True,
                    )

            return {
                "output_key": output_key,
                "intermediate_keys": intermediate_keys,
                "input_removed": input_removed,
            }

        except Exception as e:
            logger.exception(f"Pipeline failed for job {self.job_id}")
            # Don't overwrite "stopped" status — the stop endpoint already set it
            from app.workers.tasks import SyncSession
            from app.models.job import RecapJob
            with SyncSession() as session:
                current = session.execute(
                    select(RecapJob.status).where(RecapJob.id == self.job_id)
                ).scalar_one_or_none()
            if current != "stopped":
                self._update_job(
                    status="failed",
                    error_message=str(e),
                    intermediate_keys=intermediate_keys,
                )
            else:
                self._update_job(intermediate_keys=intermediate_keys)
                logger.info(f"Job {self.job_id} was stopped by user, not marking as failed")
            raise
        finally:
            if settings.preserve_pipeline_working_dir() and self.working_dir:
                logger.info(
                    "Preserved recap job workspace (DEBUG or KEEP_PIPELINE_WORKING_DIR): %s",
                    self.working_dir,
                )
            elif self.working_dir and os.path.exists(self.working_dir):
                shutil.rmtree(self.working_dir, ignore_errors=True)
