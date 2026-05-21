"""Grad-CAM saliency for the ResNet-50 CropClassifier (Slice 5d).

Returns a base64-encoded PNG showing the input image with a heatmap
overlay highlighting the regions the model attended to when picking its
top-1 class. The overlay is response-only — we don't persist 50-KB
PNGs in the predictions table.

Grad-CAM (Selvaraju et al., 2017):
  1. Register forward + full-backward hooks on the last conv block
     (ResNet-50: `model.layer4[-1]`).
  2. Forward pass; grab logits.
  3. Backprop from the top-1 logit to populate the hook gradient.
  4. Channel-wise weights = mean of gradients across spatial dims.
  5. CAM = ReLU(sum(w_c · activation_c)).
  6. Normalise 0..1, resize to 224×224, colormap, alpha-blend.

Lazy torch import — module is importable without torch installed; in
that case `compute_gradcam` returns None instead of raising.
"""
from __future__ import annotations

import base64
import io
import logging
from typing import Any


log = logging.getLogger(__name__)


OVERLAY_ALPHA: float = 0.45
TARGET_SIZE: int = 224


def compute_gradcam(
    *,
    model: Any,
    device: Any,
    transform: Any,
    image_bytes: bytes,
) -> str | None:
    """Return a base64 PNG of the Grad-CAM overlay, or None on any failure.

    Defensive: every failure mode (decode error, hook miss, gradient
    NaN, encode error) is logged and downgraded to None so an
    explainability hiccup never breaks the predict call itself.
    """
    try:
        import numpy as np
        import torch
        from PIL import Image
    except ImportError:
        return None

    try:
        with Image.open(io.BytesIO(image_bytes)) as raw:
            img = raw.convert("RGB").resize((TARGET_SIZE, TARGET_SIZE))
            original = np.array(img, dtype=np.uint8)

        tensor = transform(img).unsqueeze(0).to(device)
        # Grad-CAM needs gradients on the input pathway, not on the
        # input tensor itself — we backprop through the model.
        target_layer = _last_conv_block(model)

        captured: dict[str, Any] = {}

        def fwd_hook(_module, _inputs, output):
            captured["activation"] = output

        def bwd_hook(_module, _grad_in, grad_out):
            captured["gradient"] = grad_out[0]

        f_handle = target_layer.register_forward_hook(fwd_hook)
        b_handle = target_layer.register_full_backward_hook(bwd_hook)

        try:
            model.zero_grad()
            logits = model(tensor)
            top1 = int(logits.argmax(dim=1).item())
            logits[0, top1].backward()
        finally:
            f_handle.remove()
            b_handle.remove()

        if "activation" not in captured or "gradient" not in captured:
            log.warning("Grad-CAM hooks did not fire — skipping saliency.")
            return None

        act = captured["activation"][0]      # (C, H, W)
        grad = captured["gradient"][0]       # (C, H, W)
        weights = grad.mean(dim=(1, 2))      # (C,)
        cam = torch.relu((weights[:, None, None] * act).sum(dim=0)).detach()
        cam_min, cam_max = float(cam.min()), float(cam.max())
        if cam_max - cam_min < 1e-8:
            log.warning("Grad-CAM produced a flat heatmap — skipping.")
            return None
        cam = (cam - cam_min) / (cam_max - cam_min)
        cam_np = cam.detach().cpu().numpy().astype(np.float32)

        cam_img = Image.fromarray((cam_np * 255).astype(np.uint8)).resize(
            (TARGET_SIZE, TARGET_SIZE), Image.BILINEAR,
        )
        heatmap = _jet_colormap(np.array(cam_img, dtype=np.uint8))
        blended = (
            OVERLAY_ALPHA * heatmap.astype(np.float32)
            + (1.0 - OVERLAY_ALPHA) * original.astype(np.float32)
        ).clip(0, 255).astype(np.uint8)

        out = io.BytesIO()
        Image.fromarray(blended).save(out, format="PNG", optimize=True)
        return base64.b64encode(out.getvalue()).decode("ascii")
    except Exception as exc:  # noqa: BLE001 — never let saliency break predict
        log.warning("Grad-CAM failed: %s", exc)
        return None


def _last_conv_block(model: Any) -> Any:
    """Return the last residual block of a ResNet-50.

    Path: model.layer4[-1].conv3 is the final 1×1 conv; we hook on the
    block itself so the activation map keeps spatial dims at 7×7."""
    return model.layer4[-1]


def _jet_colormap(gray: Any) -> Any:
    """Piecewise jet-style colormap. Input: (H, W) uint8. Output: (H, W, 3) uint8.

    Lightweight enough that we don't need matplotlib as a dependency."""
    import numpy as np
    g = gray.astype(np.float32) / 255.0
    r = np.clip(1.5 * g - 0.5, 0.0, 1.0)
    grn = np.clip(1.0 - np.abs(2.0 * g - 1.0), 0.0, 1.0)
    b = np.clip(1.0 - 1.5 * g, 0.0, 1.0)
    return (np.stack([r, grn, b], axis=-1) * 255).astype(np.uint8)
