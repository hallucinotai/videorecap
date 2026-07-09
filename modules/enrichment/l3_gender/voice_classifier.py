"""Lazy-loaded gender classifier using prithivMLmods/Gender-Classifier-Mini (SigLIP image model)."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_MODEL_ID = "prithivMLmods/Gender-Classifier-Mini"
# Class 0: Female, Class 1: Male (per model card)
_CLASS_ID_TO_GENDER = {0: "female", 1: "male"}
MIN_GENDER_CONFIDENCE = 0.55

_model: Any = None
_processor: Any = None
_device: Any = None
_load_error: str | None = None


def torch_available() -> bool:
    try:
        import torch  # noqa: F401

        return True
    except ImportError:
        return False


def model_load_error() -> str | None:
    return _load_error


def _get_model() -> tuple[Any, Any, Any]:
    global _model, _processor, _device, _load_error
    if _load_error:
        raise RuntimeError(_load_error)
    if _model is not None and _processor is not None and _device is not None:
        return _model, _processor, _device

    try:
        import torch
        import safetensors  # noqa: F401
        from PIL import Image  # noqa: F401
        from transformers import AutoImageProcessor, SiglipForImageClassification  # noqa: F401
    except ImportError as exc:
        _load_error = (
            "Gender classifier dependencies missing "
            f"(install torch, transformers, pillow, safetensors): {exc}"
        )
        raise RuntimeError(_load_error) from exc

    from transformers import AutoImageProcessor, SiglipForImageClassification

    try:
        _device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        _processor = AutoImageProcessor.from_pretrained(_MODEL_ID)
        _model = SiglipForImageClassification.from_pretrained(_MODEL_ID)
        _model.to(_device)
        _model.eval()
    except Exception as exc:
        _load_error = f"Failed to load gender classifier {_MODEL_ID}: {exc}"
        logger.exception(_load_error)
        raise RuntimeError(_load_error) from exc

    return _model, _processor, _device


def classify_image(path: str) -> tuple[str, float]:
    """Classify gender; prefers InsightFace genderage on detected faces, else SigLIP."""
    insight = classify_image_insightface(path)
    if insight is not None:
        return insight
    return classify_image_siglip(path)


def classify_image_insightface(path: str) -> tuple[str, float] | None:
    """Use InsightFace genderage when a face is detected in the image."""
    try:
        import cv2
        from modules.enrichment.l3_gender.frame_extractor import _get_face_app
    except ImportError:
        return None

    image = cv2.imread(path)
    if image is None:
        return None
    faces = _get_face_app().get(image)
    if not faces:
        return None
    face = max(faces, key=lambda item: float(getattr(item, "det_score", 0.0)))
    gender = "male" if int(getattr(face, "gender", 0)) == 1 else "female"
    confidence = round(float(getattr(face, "det_score", 0.0)), 2)
    if confidence < MIN_GENDER_CONFIDENCE:
        return "unknown", 0.0
    return gender, confidence


def classify_image_siglip(path: str) -> tuple[str, float]:
    """
    Classify a face/frame image as male or female via SigLIP.

    Returns (gender, confidence) where gender is 'male' | 'female' and confidence is 0–1.
    """
    import torch
    from PIL import Image

    model, processor, device = _get_model()
    image = Image.open(path).convert("RGB")
    inputs = processor(images=image, return_tensors="pt")
    inputs = {key: value.to(device) for key, value in inputs.items()}

    model.eval()
    with torch.no_grad():
        logits = model(**inputs).logits
        probs = torch.softmax(logits, dim=1)
        confidence, pred = probs.max(1)
        gender = _CLASS_ID_TO_GENDER[int(pred.item())]
        confidence = round(float(confidence.item()), 2)
        if confidence < MIN_GENDER_CONFIDENCE:
            return "unknown", 0.0
        return gender, confidence


def classify_clip(path: str) -> tuple[str, float]:
    """Backward-compatible alias — expects an image path."""
    return classify_image(path)


def reset_model_cache() -> None:
    """Clear cached model (for tests)."""
    global _model, _processor, _device, _load_error
    _model = None
    _processor = None
    _device = None
    _load_error = None
