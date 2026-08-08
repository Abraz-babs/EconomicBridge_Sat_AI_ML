"""ResNet-50 crop disease classifier (CropGuard, Q2 deliverable).

Three execution modes picked by `_load()`:
  trained  — apps/ml/artifacts/crop_classifier.pth on disk (Slice 5b)
  untuned  — torch installed, no artifact → ImageNet backbone + random head.
             requires_human_review stays True; never auto-routed.
  stub     — torch not installed (CI). Deterministic-from-image-hash probs.

Inference contract: `ModelPrediction` (CLAUDE.md §9). Top-K rides in the
`features` dict so the router can persist as JSONB. Grad-CAM saliency
(Slice 5d) is response-only via `compute_saliency()`.
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

# MEASURED LIMITATION — read before quoting this model's accuracy anywhere.
#
# Tested 2026-08-02 against public reference imagery, no training data reused:
#   * PlantVillage-style images (one detached leaf, plain background):
#     12 of 12 correct, confidence 0.85-0.999.
#   * Real field photographs of maize (Wikimedia): 0 of 3 correct. All three
#     put a cassava class in the top-3; one returned cassava_healthy at 0.770.
#
# The cause is dataset composition rather than code. Maize and tomato come from
# PlantVillage, which is laboratory imagery; cassava, rice and plantain come
# from field-collected Kaggle sets. The crops are therefore separable by
# PHOTOGRAPHIC STYLE before a single leaf is examined, and the network learned
# that shortcut — anything that looks like a real field photo drifts to cassava.
#
# So the validation accuracy is honest about its dataset and says nothing about
# field performance. Do not present a field-photo diagnosis as operational until
# the model is retrained on field-collected imagery for EVERY class.
VALIDATED_DOMAIN = (
    "Validated on laboratory leaf imagery (single leaf, plain background) only. "
    "Unreliable on real field photographs, where it tends toward cassava — "
    "measured 2026-08-02. Retraining on field imagery is required before field use."
)


# ─── Guards against confidently answering the wrong crop ──────────────────
#
# Until retraining breaks the style/crop shortcut described above, two cheap
# guards stop the failure being INVISIBLE to the user. Neither improves the
# model; both stop it asserting something it has not earned.
#
# The important one is the crop mass. A plain confidence threshold is close to
# useless here because the model is confidently WRONG — it returned
# cassava_healthy at 0.770 on a maize field photo. But when the operator tells
# us the crop, the probability the model puts on THAT crop's classes is a real
# out-of-distribution signal: 0.770 on cassava with ~0.02 spread across every
# maize class does not mean "the best maize class"; it means the model does not
# recognise this as maize at all, and the honest answer is to say so.
MIN_CROP_MASS = 0.15

# With no declared crop there is nothing to check the model against, so we fall
# back to confidence alone and set the bar high. Deliberately conservative:
# a refusal costs a retake, a wrong diagnosis costs a season.
MIN_CONFIDENCE_WITHOUT_CROP = 0.60


def crop_of(class_name: str) -> str:
    """The crop a class belongs to — 'maize_northern_blight' -> 'maize'."""
    return class_name.split("_", 1)[0]


SUPPORTED_CROPS: tuple[str, ...] = tuple(
    dict.fromkeys(crop_of(c) for c in CROP_CLASSES)
)


def normalise_crop(raw: str | None) -> str | None:
    """Map free text from the operator to a supported crop, else None.

    The dashboard field is free text ("e.g. maize"), so accept the obvious
    variants rather than silently ignoring a usable answer. None means "not
    stated or not one of ours" — never a guess.
    """
    if not raw:
        return None
    s = raw.strip().lower()
    if not s:
        return None
    aliases = {"corn": "maize", "manioc": "cassava", "yuca": "cassava",
               "banana": "plantain", "paddy": "rice", "tomatoes": "tomato"}
    s = aliases.get(s, s)
    return s if s in SUPPORTED_CROPS else None


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
        crop: str | None = None,
    ) -> tuple[ModelPrediction, list[CropTopKEntry]]:
        """Run inference on one image. Returns (prediction, top_k_entries).

        `crop` is what the operator says they photographed. When it names a
        supported crop the classes are restricted to it — the model may no
        longer answer cassava for a maize leaf — and the answer is withheld
        entirely if the model put almost no probability on that crop. See
        MIN_CROP_MASS.
        """
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

        declared = normalise_crop(crop)
        crop_mass = (
            sum(p for c, p in zip(CROP_CLASSES, probabilities)
                if crop_of(c) == declared)
            if declared else None
        )

        if declared is not None:
            # Restrict to the declared crop and renormalise, so the reported
            # confidence is "which disease of THIS crop", not a number borrowed
            # from a crop the operator did not photograph.
            masked = [p if crop_of(c) == declared else 0.0
                      for c, p in zip(CROP_CLASSES, probabilities)]
            total = sum(masked)
            if total > 0:
                probabilities = [p / total for p in masked]

        topk_entries = _top_k_entries(probabilities, k=k)
        top1 = topk_entries[0]
        confidence = top1.probability

        # Withhold rather than assert. Two independent reasons:
        #   * the operator named a crop the model barely recognises here;
        #   * no crop was named and the model is not confident on its own.
        #
        # Only a TRAINED model has uncertainty worth acting on. In stub and
        # untuned modes the "probabilities" are a deterministic hash of the
        # image, so thresholding them would be theatre — those modes already
        # declare themselves via execution_mode and requires_human_review.
        abstain_reason: str | None = None
        if self._mode != "trained":
            pass
        elif declared is not None and (crop_mass or 0.0) < MIN_CROP_MASS:
            abstain_reason = (
                f"This does not look like {declared} to the model "
                f"({(crop_mass or 0.0):.0%} of its confidence went to {declared} "
                f"classes). Re-take the photo with one leaf filling the frame, "
                f"or check the crop selection."
            )
        elif declared is None and confidence < MIN_CONFIDENCE_WITHOUT_CROP:
            abstain_reason = (
                "Not confident enough to name a disease. Select the crop and "
                "re-take the photo with one leaf filling the frame."
            )
        # `prediction` = total probability mass on disease classes. Higher =
        # more concerning across all confidence levels (see test_crop_classifier).
        prediction_score = _disease_probability_mass(probabilities)

        band = band_for_confidence(confidence)
        requires_review = (
            (self._mode != "trained") or (band != "HIGH")
            or abstain_reason is not None
        )

        elapsed_ms = int((time.monotonic() - started) * 1000)
        return (
            ModelPrediction(
                model_name=MODEL_NAME,
                model_version=self.version,
                tenant_id=tenant_id,
                prediction=float(prediction_score),
                confidence=float(confidence),
                shap_values={},  # CNN saliency comes via compute_saliency()
                input_hash=image.image_sha256,
                inference_time_ms=elapsed_ms,
                timestamp=utcnow(),
                requires_human_review=requires_review,
                confidence_band=band,
                features={
                    # None when abstaining: downstream must not be able to read
                    # a class name off a result we refused to stand behind.
                    "predicted_class": (
                        None if abstain_reason else top1.class_name
                    ),
                    "abstained": abstain_reason is not None,
                    "abstain_reason": abstain_reason,
                    "declared_crop": declared,
                    "declared_crop_mass": (
                        None if crop_mass is None else round(float(crop_mass), 4)
                    ),
                    "image_source": image.image_source,
                    "execution_mode": self._mode,
                    # Travels with every stored prediction so the limitation is
                    # in the DATA, not only in UI copy that a future screen may
                    # not carry. See VALIDATED_DOMAIN.
                    "validated_domain": VALIDATED_DOMAIN,
                    "top_k": [
                        {"class_name": e.class_name, "probability": e.probability}
                        for e in topk_entries
                    ],
                },
            ),
            topk_entries,
        )

    # ── Loader ──────────────────────────────────────────────────────────
    # (S3 fetch helper is module-level below the class.)

    def _load(self) -> None:
        if self._mode is not None:
            return

        settings = get_settings()
        artifact = Path(settings.model_dir) / "crop_classifier.pth"
        if not artifact.exists() and settings.model_s3_uri:
            _fetch_artifact_from_s3(settings.model_s3_uri, artifact)

        try:
            import torch  # noqa: F401
        except ImportError:
            log.warning("crop_classifier: torch missing → STUB mode (review=True).")
            self._mode = "stub"
            return

        try:
            self._build_torch_model(artifact_path=artifact)
        except Exception as exc:  # noqa: BLE001 — fall back to stub gracefully
            log.warning("crop_classifier: torch init failed (%s) → STUB", exc)
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

    def compute_saliency(self, image_bytes: bytes) -> str | None:
        """Grad-CAM overlay as a base64 PNG. None in stub mode."""
        self._load()
        if self._mode == "stub" or self._model is None:
            return None
        from models.crop_saliency import compute_gradcam
        return compute_gradcam(
            model=self._model, device=self._device,
            transform=self._transform, image_bytes=image_bytes,
        )

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


# ─── S3 artifact fetch ────────────────────────────────────────────────────


def _fetch_artifact_from_s3(s3_uri: str, dest: Path) -> None:
    """Download the trained weights from S3 to `dest` (best-effort).

    The ~94 MB .pth is gitignored, so deployed containers pull it at first
    model load via MODEL_S3_URI (task role provides credentials). Never
    raises — on any failure the loader proceeds and lands in UNTUNED mode,
    which the response's model_version surfaces honestly.

    Args:
        s3_uri: Location like ``s3://bucket/ml/crop_classifier.pth``.
        dest: Local artifact path to write.
    """
    try:
        import boto3

        bucket_key = s3_uri.removeprefix("s3://")
        bucket, _, key = bucket_key.partition("/")
        if not bucket or not key:
            log.warning("crop_classifier: malformed MODEL_S3_URI %r", s3_uri)
            return
        dest.parent.mkdir(parents=True, exist_ok=True)
        log.info("crop_classifier: fetching weights from %s ...", s3_uri)
        boto3.client("s3").download_file(bucket, key, str(dest))
        log.info("crop_classifier: weights downloaded to %s", dest)
    except Exception as exc:  # noqa: BLE001 — model fetch must not crash the service
        log.warning("crop_classifier: S3 fetch failed (%s) → continuing without", exc)


# ─── Singleton ────────────────────────────────────────────────────────────


_CLASSIFIER: CropClassifier | None = None


def get_classifier() -> CropClassifier:
    """Process-wide singleton (mirrors get_predictor for the RF model)."""
    global _CLASSIFIER
    if _CLASSIFIER is None:
        _CLASSIFIER = CropClassifier()
    return _CLASSIFIER
