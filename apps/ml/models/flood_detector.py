"""U-Net flood-segmentation model for ShockGuard (Module 05).

Maps a 2-channel Sentinel-1 GRD chip (VV + VH backscatter, dB) to a
per-pixel flood-probability mask. Trained on Sen1Floods11 (public, ~15 GB:
512×512 S1 chips + hand-labelled flood masks).

STATUS: prep — ready for a GPU training run, not yet trained. ShockGuard
runs a statistical detector on real Sentinel-1 data today; this U-Net is the
upgrade that produces actual flood polygons. `torch` is imported lazily so
this module (and the ml service) load without the deep-learning stack
installed; `FloodDetector` falls back to a clear stub until an artifact exists.

To train: see apps/ml/scripts/train_flood_detector.py (needs torch +
torchvision + a CUDA GPU + the Sen1Floods11 dataset).
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

MODEL_NAME = "flood_detector"
MODEL_VERSION = "0.0.0-untrained"
ARTIFACT_FILENAME = "flood_detector.pth"

# Sentinel-1 input: 2 channels (VV, VH); binary flood mask out.
IN_CHANNELS = 2
OUT_CHANNELS = 1
# Probability ≥ this is "flooded" for the binarised mask.
FLOOD_THRESHOLD = 0.5


def build_unet(in_channels: int = IN_CHANNELS, out_channels: int = OUT_CHANNELS):
    """Construct the U-Net (torch imported lazily). Compact 4-level encoder/
    decoder with skip connections — plenty for 512×512 SAR flood masks and
    light enough to train on a single mid-range GPU."""
    import torch.nn as nn

    def conv_block(ci: int, co: int) -> "nn.Module":
        return nn.Sequential(
            nn.Conv2d(ci, co, 3, padding=1), nn.BatchNorm2d(co), nn.ReLU(inplace=True),
            nn.Conv2d(co, co, 3, padding=1), nn.BatchNorm2d(co), nn.ReLU(inplace=True),
        )

    class UNet(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.e1 = conv_block(in_channels, 32)
            self.e2 = conv_block(32, 64)
            self.e3 = conv_block(64, 128)
            self.e4 = conv_block(128, 256)
            self.pool = nn.MaxPool2d(2)
            self.up3 = nn.ConvTranspose2d(256, 128, 2, stride=2)
            self.d3 = conv_block(256, 128)
            self.up2 = nn.ConvTranspose2d(128, 64, 2, stride=2)
            self.d2 = conv_block(128, 64)
            self.up1 = nn.ConvTranspose2d(64, 32, 2, stride=2)
            self.d1 = conv_block(64, 32)
            self.head = nn.Conv2d(32, out_channels, 1)

        def forward(self, x):  # noqa: ANN001
            import torch
            c1 = self.e1(x)
            c2 = self.e2(self.pool(c1))
            c3 = self.e3(self.pool(c2))
            c4 = self.e4(self.pool(c3))
            u3 = self.d3(torch.cat([self.up3(c4), c3], dim=1))
            u2 = self.d2(torch.cat([self.up2(u3), c2], dim=1))
            u1 = self.d1(torch.cat([self.up1(u2), c1], dim=1))
            return self.head(u1)  # logits; apply sigmoid for probability

    return UNet()


class FloodDetector:
    """Lazy-loaded flood mask predictor. Stub until an artifact is trained."""

    def __init__(self, *, artifact_dir: str | Path | None = None) -> None:
        self._artifact_dir = Path(artifact_dir) if artifact_dir else None
        self._model: Any | None = None
        self._loaded = False

    @property
    def trained(self) -> bool:
        path = self._artifact_path()
        return path is not None and path.exists()

    def _artifact_path(self) -> Path | None:
        if self._artifact_dir is None:
            try:
                from config import get_settings
                self._artifact_dir = Path(get_settings().model_dir)
            except Exception:  # noqa: BLE001
                return None
        return self._artifact_dir / ARTIFACT_FILENAME

    def _load(self) -> None:
        if self._loaded:
            return
        path = self._artifact_path()
        if path is None or not path.exists():
            log.info("flood_detector: no artifact at %s — stub mode", path)
            self._loaded = True
            return
        import torch
        model = build_unet()
        model.load_state_dict(torch.load(path, map_location="cpu"))
        model.eval()
        self._model = model
        self._loaded = True
        log.info("flood_detector: loaded artifact from %s", path)

    def predict_mask(self, chip):  # noqa: ANN001 — np.ndarray [2,H,W]
        """Return a per-pixel flood-probability mask for a 2×H×W S1 chip.

        Raises NotImplementedError in stub mode (no artifact) rather than
        emitting a fake mask — callers should fall back to the statistical
        detector until the model is trained.
        """
        self._load()
        if self._model is None:
            raise NotImplementedError(
                "FloodDetector has no trained artifact. Train via "
                "apps/ml/scripts/train_flood_detector.py on a GPU, or use the "
                "statistical flood detector (services/shock_detector.py)."
            )
        import torch
        with torch.no_grad():
            x = torch.as_tensor(chip, dtype=torch.float32).unsqueeze(0)
            return torch.sigmoid(self._model(x)).squeeze().cpu().numpy()
