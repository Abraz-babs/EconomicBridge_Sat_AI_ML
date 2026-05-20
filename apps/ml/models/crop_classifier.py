"""ResNet-50 crop disease classifier (CropGuard, Q2 deliverable).

Three execution modes, picked by `_load()`:

  1. `trained`  — apps/ml/artifacts/crop_classifier.pth on disk → real
                  inference. Q2-end goal; populated by Slice 5b.
  2. `untuned`  — torch installed, no artifact → ImageNet backbone +
                  randomly-initialised 12-class head. `requires_human_review`
                  is True for every call so dashboards never mistake these
                  for production output.
  3. `stub`     — torch not installed (CI / minimal dev) → deterministic-
                  from-image-hash probabilities. Honest contract, zero deps.

Inference contract is `ModelPrediction` (CLAUDE.md §9); Top-K probabilities
ride in the `features` dict so the router can persist them as JSONB.
"""
from __future__ import annotations

import hashlib
import io
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from config import get_settings
from models.prediction import (
    ModelPrediction,
    band_for_confidence,
    utcnow,
)

log = logging.getLogger(__name__)


MODEL_NAME = "crop_classifier"

# 12 West African staples + their top diseases. Order is the model output
# index — changing it is a breaking change.
CROP_CLASSES: tuple[str, ...] = (
    "cassava_healthy",
    "cassava_mosaic_disease",
    "cassava_brown_streak",
    "maize_healthy",
    "maize_streak_virus",
    "maize_northern_blight",
    "rice_healthy",
    "rice_blast",
    "tomato_healthy",
    "tomato_late_blight",
    "plantain_healthy",
    "plantain_black_sigatoka",
)

ExecutionMode = Literal["trained", "untuned", "stub"]


# ─── Dataclasses ──────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class CropPredictionInput:
    """Pre-validated input bundle for one CropClassifier.predict call."""

    image_bytes: bytes
    image_sha256: str
    image_source: Literal["s3", "inline"]
    image_s3_bucket: str | None = None
    image_s3_key: str | None = None


@dataclass(frozen=True, slots=True)
class CropTopKEntry:
    class_name: str
    probability: float


# ─── Classifier ───────────────────────────────────────────────────────────


class CropClassifier:
    """Lazy-loaded ResNet-50 (or stub). One instance per process."""

    def __init__(self) -> None:
        self._mode: ExecutionMode | None = None
        self._model: Any = None
        self._device: Any = None
        self._transform: Any = None

    @property
    def mode(self) -> ExecutionMode:
        if self._mode is None:
            self._load()
        assert self._mode is not None
        return self._mode

    @property
    def version(self) -> str:
        return f"0.1.0-{self.mode}"

    def predict(
        self,
        *,
        tenant_id: str,
        image: CropPredictionInput,
        top_k: int | None = None,
    ) -> tuple[ModelPrediction, list[CropTopKEntry]]:
        """Run inference on one image. Returns (prediction, top_k_entries)."""
        settings = get_settings()
        k = top_k if top_k is not None else settings.crop_top_k_classes
        if not 1 <= k <= len(CROP_CLASSES):
            raise ValueError(f"top_k must be 1..{len(CROP_CLASSES)} (got {k})")

        self._load()
        started = time.monotonic()

        if self._mode == "stub":
            probabilities = _stub_probabilities(image.image_sha256)
        else:
            probabilities = self._torch_inference(image.image_bytes)

        topk_entries = _top_k_entries(probabilities, k=k)
        top1 = topk_entries[0]
        confidence = top1.probability
        # `prediction` = total probability mass on disease classes. Higher =
        # more concerning. A confident healthy top-1 drains most mass into
        # the healthy classes → low prediction; a disease top-1 (or even
        # uncertain spread) keeps disease mass high → high prediction.
        prediction_score = _disease_probability_mass(probabilities)

        band = band_for_confidence(confidence)
        # Untuned + stub modes never auto-route.
        requires_review = (self._mode != "trained") or (band != "HIGH")

        elapsed_ms = int((time.monotonic() - started) * 1000)
        return (
            ModelPrediction(
                model_name=MODEL_NAME,
                model_version=self.version,
                tenant_id=tenant_id,
                prediction=float(prediction_score),
                confidence=float(confidence),
                shap_values={},  # Grad-CAM saliency arrives in Slice 5e
                input_hash=image.image_sha256,
                inference_time_ms=elapsed_ms,
                timestamp=utcnow(),
                requires_human_review=requires_review,
                confidence_band=band,
                features={
                    "predicted_class": top1.class_name,
                    "image_source": image.image_source,
                    "execution_mode": self._mode,
                    "top_k": [
                        {"class_name": e.class_name, "probability": e.probability}
                        for e in topk_entries
                    ],
                },
            ),
            topk_entries,
        )

    # ── Loader ──────────────────────────────────────────────────────────

    def _load(self) -> None:
        if self._mode is not None:
            return

        settings = get_settings()
        artifact = Path(settings.model_dir) / "crop_classifier.pth"

        try:
            import torch  # noqa: F401
        except ImportError:
            log.warning(
                "crop_classifier: torch not installed → STUB mode "
                "(requires_human_review will be True for every call)."
            )
            self._mode = "stub"
            return

        try:
            self._build_torch_model(artifact_path=artifact)
        except Exception as exc:  # noqa: BLE001 — fall back to stub gracefully
            log.warning(
                "crop_classifier: torch init failed (%s) → falling back "
                "to STUB mode", exc,
            )
            self._mode = "stub"

    def _build_torch_model(self, *, artifact_path: Path) -> None:
        """Construct the torchvision ResNet-50 + 12-class head."""
        import torch
        from torchvision import models, transforms

        self._device = torch.device("cpu")
        backbone = models.resnet50(weights=None)
        in_features = backbone.fc.in_features
        backbone.fc = torch.nn.Linear(in_features, len(CROP_CLASSES))
        backbone.eval()

        if artifact_path.exists():
            log.info("crop_classifier: loading weights from %s", artifact_path)
            state = torch.load(
                artifact_path, map_location=self._device, weights_only=True,
            )
            backbone.load_state_dict(state)
            self._mode = "trained"
        else:
            log.warning(
                "crop_classifier: no artifact at %s → UNTUNED mode (random "
                "head). Predictions are NOT operational; train via Slice 5b.",
                artifact_path,
            )
            self._mode = "untuned"

        self._model = backbone.to(self._device)
        self._transform = transforms.Compose([
            transforms.Resize(256),
            transforms.CenterCrop(224),
            transforms.ToTensor(),
            transforms.Normalize(
                mean=[0.485, 0.456, 0.406],
                std=[0.229, 0.224, 0.225],
            ),
        ])

    def _torch_inference(self, image_bytes: bytes) -> list[float]:
        """One forward pass through ResNet-50. Returns 12 probabilities."""
        import torch
        from PIL import Image

        with Image.open(io.BytesIO(image_bytes)) as raw:
            img = raw.convert("RGB")
            tensor = self._transform(img).unsqueeze(0).to(self._device)

        with torch.no_grad():
            logits = self._model(tensor)
            probabilities = torch.softmax(logits, dim=1).squeeze(0).tolist()
        return [float(p) for p in probabilities]


# ─── Stub-mode + helpers ──────────────────────────────────────────────────


def _stub_probabilities(image_sha256: str) -> list[float]:
    """Deterministic class probs from the image hash. Same hash → same vector.

    Keeps the HTTP contract round-trippable in CI without torch, while still
    varying output across different images so the dashboard reacts to input."""
    digest = bytes.fromhex(image_sha256)
    raw = [digest[i % len(digest)] + 1 for i in range(len(CROP_CLASSES))]
    total = float(sum(raw))
    probs = [r / total for r in raw]
    # Bias the winner so the dashboard renders a clear top-1.
    top_idx = max(range(len(probs)), key=lambda i: probs[i])
    boost = 0.15 * (1.0 - probs[top_idx])
    probs[top_idx] += boost
    s = sum(probs)
    return [p / s for p in probs]


def _disease_probability_mass(probabilities: list[float]) -> float:
    """Sum probabilities of every non-healthy class."""
    return float(sum(
        p for p, name in zip(probabilities, CROP_CLASSES)
        if not name.endswith("_healthy")
    ))


def _top_k_entries(
    probabilities: list[float], *, k: int
) -> list[CropTopKEntry]:
    indexed = sorted(
        enumerate(probabilities), key=lambda iv: iv[1], reverse=True
    )
    return [
        CropTopKEntry(class_name=CROP_CLASSES[i], probability=float(p))
        for i, p in indexed[:k]
    ]


def hash_image_bytes(blob: bytes) -> str:
    """SHA-256 of image bytes — used for replay + the input_hash field."""
    return hashlib.sha256(blob).hexdigest()


# ─── Singleton ────────────────────────────────────────────────────────────


_CLASSIFIER: CropClassifier | None = None


def get_classifier() -> CropClassifier:
    """Process-wide singleton (mirrors get_predictor for the RF model)."""
    global _CLASSIFIER
    if _CLASSIFIER is None:
        _CLASSIFIER = CropClassifier()
    return _CLASSIFIER
