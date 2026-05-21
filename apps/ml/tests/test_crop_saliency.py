"""Tests for models/crop_saliency.py (Grad-CAM).

Two paths:
  * Fast: torch import is mocked-out → compute_gradcam returns None.
    This is what CI hits.
  * Slow: real torch + real ResNet-50 → produces a real PNG. Runs the
    full Grad-CAM pipeline end-to-end with synthetic inputs. Verifies
    the output is a parseable 224×224 PNG.
"""
from __future__ import annotations

import base64
import io

import pytest

from models.crop_saliency import compute_gradcam


# ─── Fast path: torch unavailable ──────────────────────────────────────────


def test_compute_gradcam_returns_none_when_torch_missing(monkeypatch):
    """Make `import torch` fail → function must return None, not raise."""
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "torch":
            raise ImportError("torch is not available in this test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    result = compute_gradcam(
        model=None, device=None, transform=None,
        image_bytes=b"\x00" * 16,
    )
    assert result is None


def test_compute_gradcam_returns_none_on_undecodable_image():
    """Garbage bytes → PIL.Image.open raises → defensive return None."""
    result = compute_gradcam(
        model=None, device=None, transform=None,
        image_bytes=b"not-an-image",
    )
    assert result is None


# ─── Slow path: real torch + ResNet-50 ──────────────────────────────────


pytest.importorskip("torch")
pytest.importorskip("torchvision")
pytest.importorskip("PIL.Image")


@pytest.mark.slow
def test_compute_gradcam_real_resnet50_produces_valid_png():
    """End-to-end: real ResNet-50 + a synthetic image → base64 PNG."""
    import torch
    import numpy as np
    from PIL import Image
    from torchvision import models, transforms

    # ImageNet-pretrained ResNet-50 + 12-class head (mirrors what
    # CropClassifier._build_torch_model does).
    backbone = models.resnet50(weights=models.ResNet50_Weights.DEFAULT)
    backbone.fc = torch.nn.Linear(backbone.fc.in_features, 12)
    backbone.eval()
    device = torch.device("cpu")

    transform = transforms.Compose([
        transforms.Resize(256),
        transforms.CenterCrop(224),
        transforms.ToTensor(),
        transforms.Normalize(
            mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225],
        ),
    ])

    # Synthetic 64×64 RGB image (Grad-CAM resizes internally to 224).
    rng = np.random.default_rng(seed=42)
    arr = rng.integers(0, 256, size=(64, 64, 3), dtype=np.uint8)
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, format="PNG")
    image_bytes = buf.getvalue()

    result = compute_gradcam(
        model=backbone, device=device, transform=transform,
        image_bytes=image_bytes,
    )

    assert result is not None, "Grad-CAM must produce an overlay"
    raw = base64.b64decode(result)
    out_img = Image.open(io.BytesIO(raw))
    out_img.verify()  # validates PNG structure
    # Re-open since verify() closes the file pointer.
    out_img = Image.open(io.BytesIO(raw))
    assert out_img.size == (224, 224)
    assert out_img.mode == "RGB"


@pytest.mark.slow
def test_compute_gradcam_deterministic_for_same_input(monkeypatch):
    """Same image + same (deterministic) model → same overlay bytes.

    ResNet-50 weights are not deterministic across torchvision releases
    but for a fixed model instance the forward + backward pass is. So
    two calls in a row with the same model must produce byte-identical
    base64 strings."""
    import torch
    from PIL import Image
    from torchvision import models, transforms

    torch.manual_seed(42)
    backbone = models.resnet50(weights=None)
    backbone.fc = torch.nn.Linear(backbone.fc.in_features, 12)
    backbone.eval()
    transform = transforms.Compose([
        transforms.Resize(256),
        transforms.CenterCrop(224),
        transforms.ToTensor(),
        transforms.Normalize(
            mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225],
        ),
    ])
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), color=(70, 140, 60)).save(buf, format="PNG")
    image_bytes = buf.getvalue()

    a = compute_gradcam(
        model=backbone, device=torch.device("cpu"),
        transform=transform, image_bytes=image_bytes,
    )
    b = compute_gradcam(
        model=backbone, device=torch.device("cpu"),
        transform=transform, image_bytes=image_bytes,
    )
    assert a is not None and b is not None
    assert a == b
