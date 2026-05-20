"""Tests for scripts/crop_training.py + scripts/train_crop_classifier.py.

The big-ticket test is `test_end_to_end_tiny_train_produces_loadable_pth`:
generates a tiny synthetic dataset on disk (10 classes × 3 images each
of random RGB), trains for 1 epoch in --tiny mode, saves the resulting
state_dict, and confirms that `CropClassifier` picks it up and reports
mode='trained' on the next predict() call.

Runtime budget on a modest laptop: ~20-40 seconds for the end-to-end
test (single ResNet-50 forward pass on 30 images is what dominates;
the actual fit is trivial). Marked `slow` so day-to-day pytest runs
can `-m "not slow"` to keep iteration tight.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

# Skip the whole module if torch isn't installed — these tests need real
# training, no point in mocking that out.
torch = pytest.importorskip("torch")
np = pytest.importorskip("numpy")
PIL_Image = pytest.importorskip("PIL.Image")

from models.crop_classifier import (  # noqa: E402
    CROP_CLASSES,
    CropClassifier,
    CropPredictionInput,
)
from scripts.crop_training import (  # noqa: E402
    TrainConfig,
    build_class_remap,
    discover_class_dirs,
    train_model,
)
from scripts.train_crop_classifier import (  # noqa: E402
    build_arg_parser,
    config_from_args,
)


# ─── Synthetic dataset builder ─────────────────────────────────────────────


def _write_synthetic_dataset(
    root: Path,
    *,
    classes: list[str],
    images_per_class: int = 3,
    image_size: int = 32,
    seed: int = 0,
) -> None:
    """Write tiny RGB PNGs under root/<class_name>/img_*.png."""
    rng = np.random.default_rng(seed)
    for class_name in classes:
        class_dir = root / class_name
        class_dir.mkdir(parents=True, exist_ok=True)
        for i in range(images_per_class):
            arr = rng.integers(
                0, 256, size=(image_size, image_size, 3), dtype=np.uint8,
            )
            PIL_Image.fromarray(arr).save(class_dir / f"img_{i:03d}.png")


# ─── discover_class_dirs ──────────────────────────────────────────────────


def test_discover_class_dirs_returns_only_populated(tmp_path):
    _write_synthetic_dataset(
        tmp_path, classes=["maize_healthy", "rice_healthy"],
    )
    (tmp_path / "tomato_healthy").mkdir()  # empty — should be skipped
    found = discover_class_dirs(tmp_path, CROP_CLASSES)
    found_names = {p.name for p in found}
    assert found_names == {"maize_healthy", "rice_healthy"}


def test_discover_class_dirs_raises_when_no_classes(tmp_path):
    with pytest.raises(RuntimeError, match="No usable class subfolders"):
        discover_class_dirs(tmp_path, CROP_CLASSES)


def test_discover_class_dirs_raises_when_data_dir_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        discover_class_dirs(tmp_path / "does-not-exist", CROP_CLASSES)


# ─── build_class_remap ────────────────────────────────────────────────────


def test_build_class_remap_aligns_alphabetical_to_canonical():
    # ImageFolder gives us alphabetical order — confirm the remap rewires
    # those indices to the canonical CROP_CLASSES order.
    folder_classes = ["maize_healthy", "tomato_healthy"]
    remap = build_class_remap(
        folder_classes=folder_classes, canonical=CROP_CLASSES,
    )
    assert remap[0] == CROP_CLASSES.index("maize_healthy")
    assert remap[1] == CROP_CLASSES.index("tomato_healthy")


def test_build_class_remap_rejects_unknown_folder_class():
    with pytest.raises(ValueError, match="not in CROP_CLASSES"):
        build_class_remap(
            folder_classes=["definitely_not_a_crop"], canonical=CROP_CLASSES,
        )


# ─── CLI ──────────────────────────────────────────────────────────────────


def test_build_arg_parser_defaults():
    parser = build_arg_parser()
    args = parser.parse_args(["--data-dir", "/tmp/x"])
    assert args.data_dir == Path("/tmp/x")
    assert args.epochs > 0
    assert args.tiny is False


def test_config_from_args_defaults_output_under_artifacts():
    parser = build_arg_parser()
    args = parser.parse_args(["--data-dir", "/tmp/x"])
    config = config_from_args(args)
    assert config.output_path.name == "crop_classifier.pth"
    assert "artifacts" in str(config.output_path)


def test_config_from_args_respects_explicit_output(tmp_path):
    parser = build_arg_parser()
    args = parser.parse_args([
        "--data-dir", "/tmp/x",
        "--output", str(tmp_path / "custom.pth"),
        "--tiny",
    ])
    config = config_from_args(args)
    assert config.output_path == tmp_path / "custom.pth"
    assert config.tiny is True


# ─── End-to-end: synthetic train produces loadable .pth ───────────────────


@pytest.mark.slow
def test_end_to_end_tiny_train_produces_loadable_pth(tmp_path, monkeypatch):
    """Train on 30 synthetic images, save .pth, load via CropClassifier."""
    # Use only the FIRST 10 of the 12 canonical classes — torchvision's
    # ImageFolder needs ≥2 distinct classes; tiny mode only takes 3 steps
    # per epoch which is fine.
    classes = list(CROP_CLASSES[:10])
    _write_synthetic_dataset(
        tmp_path / "data",
        classes=classes,
        images_per_class=3,
    )

    output_path = tmp_path / "crop_classifier.pth"
    config = TrainConfig(
        data_dir=tmp_path / "data",
        output_path=output_path,
        epochs=1,
        batch_size=4,
        learning_rate=1e-3,
        val_fraction=0.2,
        seed=42,
        num_workers=0,  # avoid worker subprocess churn on Windows
        tiny=True,
    )
    result = train_model(config)

    assert output_path.exists(), "training did not write the .pth file"
    assert output_path.stat().st_size > 1_000_000, \
        "expected a multi-MB ResNet-50 state_dict, got something smaller"
    assert result.epochs_completed == 1
    assert result.train_samples > 0
    assert result.val_samples > 0

    # CropClassifier should now load it in trained mode.
    monkeypatch.setenv("MODEL_DIR", str(tmp_path))
    from config import get_settings
    get_settings.cache_clear()
    # The classifier reads model_dir from get_settings.model_dir.
    monkeypatch.setattr(
        "models.crop_classifier.get_settings",
        lambda: type(
            "S", (), {
                "model_dir": tmp_path,
                "crop_top_k_classes": 3,
            }
        )(),
    )

    classifier = CropClassifier()
    # Force fresh load (singleton state lives across tests in the same process).
    classifier._mode = None  # type: ignore[attr-defined]
    assert classifier.mode == "trained"
    assert classifier.version == "0.1.0-trained"

    # And it can run inference on a real image.
    img_bytes = (tmp_path / "data" / classes[0] / "img_000.png").read_bytes()
    img_input = CropPredictionInput(
        image_bytes=img_bytes,
        image_sha256=hashlib.sha256(img_bytes).hexdigest(),
        image_source="inline",
    )
    prediction, top_k = classifier.predict(
        tenant_id="kebbi", image=img_input, top_k=3,
    )
    assert prediction.model_version == "0.1.0-trained"
    assert prediction.features["predicted_class"] in CROP_CLASSES
    assert len(top_k) == 3
    # In trained mode, requires_human_review can be False when confidence
    # is HIGH. With 30 synthetic images we can't guarantee that — but the
    # *mechanism* must be enabled (no longer hard-True like in stub/untuned).
    # So just confirm the model_version doesn't end in "stub"/"untuned":
    assert "stub" not in prediction.model_version
    assert "untuned" not in prediction.model_version


# ─── Dev artifact: produce + check in ─────────────────────────────────────


@pytest.mark.slow
def test_dev_artifact_smoke_train(tmp_path):
    """Produce a dev-only .pth in apps/ml/artifacts/. Skipped by default —
    enable via env CROPGUARD_PRODUCE_DEV_PTH=1 when refreshing the artifact.
    The artifact lives in git and exists so CropClassifier can demo `trained`
    mode in dev environments without a real PlantVillage download.
    """
    import os
    if not os.environ.get("CROPGUARD_PRODUCE_DEV_PTH"):
        pytest.skip(
            "set CROPGUARD_PRODUCE_DEV_PTH=1 to (re)produce the dev artifact"
        )

    # Build a slightly bigger synthetic dataset so the dev artifact has
    # something resembling real fit, not 30 random images.
    classes = list(CROP_CLASSES)
    src = tmp_path / "data"
    _write_synthetic_dataset(src, classes=classes, images_per_class=10)

    artifact_dir = Path(__file__).resolve().parent.parent / "artifacts"
    output_path = artifact_dir / "crop_classifier.pth"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    # Don't blow away an existing real-data artifact if someone trained one
    # offline — they probably want to keep it.
    if output_path.exists() and not os.environ.get("CROPGUARD_FORCE"):
        pytest.skip(
            f"artifact already exists at {output_path}; "
            "set CROPGUARD_FORCE=1 to overwrite"
        )

    config = TrainConfig(
        data_dir=src,
        output_path=output_path,
        epochs=2,
        batch_size=8,
        learning_rate=1e-3,
        val_fraction=0.2,
        seed=42,
        num_workers=0,
        tiny=True,
    )
    result = train_model(config)
    assert output_path.exists()
    assert result.epochs_completed == 2
