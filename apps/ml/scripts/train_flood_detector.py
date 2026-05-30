"""Train the ShockGuard U-Net flood detector on Sen1Floods11.

PREP — ready to run on a GPU; not run in CI (needs torch + CUDA + the dataset).

Data (download once, ~15 GB):
    Sen1Floods11 — https://github.com/cloudtostreet/Sen1Floods11
    Layout expected after download:
        <data-dir>/S1Hand/*.tif      (2-band VV/VH Sentinel-1 GRD chips)
        <data-dir>/LabelHand/*.tif   (matching 0/1 flood masks, -1 = no data)
    Pair files by the shared scene id in the filename.

Run:
    pip install torch torchvision rasterio
    python -m scripts.train_flood_detector --data-dir /data/sen1floods11 \\
        --epochs 40 --batch-size 16 --device cuda
    # smoke test (no GPU, a few steps on whatever chips are present):
    python -m scripts.train_flood_detector --data-dir ./sample --tiny --device cpu

Output: apps/ml/artifacts/flood_detector.pth — FloodDetector._load() picks it
up and ShockGuard can switch flood detection from statistical → U-Net.

Loss: BCE + Dice (handles the heavy class imbalance — flood pixels are rare).
"""
from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass
from pathlib import Path

ML_ROOT = Path(__file__).resolve().parent.parent
if str(ML_ROOT) not in sys.path:
    sys.path.insert(0, str(ML_ROOT))

from models.flood_detector import ARTIFACT_FILENAME, build_unet  # noqa: E402

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class TrainConfig:
    data_dir: Path
    output: Path
    epochs: int = 40
    batch_size: int = 16
    lr: float = 1e-3
    device: str = "cuda"
    tiny: bool = False           # cap steps/epoch for a smoke run
    val_fraction: float = 0.15


def _dice_bce_loss(logits, target):  # noqa: ANN001 — torch tensors
    """BCE + soft Dice — Dice term counters flood-pixel scarcity."""
    import torch
    import torch.nn.functional as F
    bce = F.binary_cross_entropy_with_logits(logits, target)
    probs = torch.sigmoid(logits)
    inter = (probs * target).sum()
    dice = 1 - (2 * inter + 1) / (probs.sum() + target.sum() + 1)
    return bce + dice


def _build_dataset(data_dir: Path):
    """Pair S1Hand chips with LabelHand masks. Lazy torch/rasterio."""
    import numpy as np
    import rasterio
    import torch
    from torch.utils.data import Dataset

    s1_dir, label_dir = data_dir / "S1Hand", data_dir / "LabelHand"
    scenes = sorted(p.stem.replace("_S1Hand", "") for p in s1_dir.glob("*_S1Hand.tif"))
    if not scenes:
        raise FileNotFoundError(
            f"No *_S1Hand.tif under {s1_dir}. Download Sen1Floods11 first."
        )

    class S1FloodDataset(Dataset):
        def __len__(self) -> int:
            return len(scenes)

        def __getitem__(self, i: int):
            sid = scenes[i]
            with rasterio.open(s1_dir / f"{sid}_S1Hand.tif") as src:
                img = src.read().astype("float32")          # [2,H,W] VV,VH dB
            with rasterio.open(label_dir / f"{sid}_LabelHand.tif") as src:
                mask = src.read(1).astype("float32")         # [H,W], -1/0/1
            img = np.clip((img + 25.0) / 25.0, 0, 2)          # normalise dB
            valid = (mask >= 0).astype("float32")
            mask = np.clip(mask, 0, 1)
            return (
                torch.as_tensor(img),
                torch.as_tensor(mask).unsqueeze(0),
                torch.as_tensor(valid).unsqueeze(0),
            )

    return S1FloodDataset()


def train(cfg: TrainConfig) -> Path:
    import torch
    from torch.utils.data import DataLoader, random_split

    ds = _build_dataset(cfg.data_dir)
    n_val = max(1, int(len(ds) * cfg.val_fraction))
    train_ds, val_ds = random_split(ds, [len(ds) - n_val, n_val])
    dl = DataLoader(train_ds, batch_size=cfg.batch_size, shuffle=True)

    device = cfg.device if torch.cuda.is_available() or cfg.device == "cpu" else "cpu"
    model = build_unet().to(device)
    opt = torch.optim.Adam(model.parameters(), lr=cfg.lr)

    model.train()
    for epoch in range(cfg.epochs):
        running = 0.0
        for step, (img, mask, valid) in enumerate(dl):
            if cfg.tiny and step >= 3:
                break
            img, mask, valid = img.to(device), mask.to(device), valid.to(device)
            opt.zero_grad()
            logits = model(img)
            loss = _dice_bce_loss(logits * valid, mask * valid)
            loss.backward()
            opt.step()
            running += float(loss)
        log.info("epoch %d/%d loss=%.4f", epoch + 1, cfg.epochs, running / max(1, step + 1))
        if cfg.tiny:
            break

    cfg.output.parent.mkdir(parents=True, exist_ok=True)
    torch.save(model.state_dict(), cfg.output)
    log.info("saved flood_detector artifact → %s", cfg.output)
    return cfg.output


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data-dir", required=True, type=Path)
    p.add_argument("--output", type=Path, default=ML_ROOT / "artifacts" / ARTIFACT_FILENAME)
    p.add_argument("--epochs", type=int, default=40)
    p.add_argument("--batch-size", type=int, default=16)
    p.add_argument("--lr", type=float, default=1e-3)
    p.add_argument("--device", default="cuda")
    p.add_argument("--tiny", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    args = build_arg_parser().parse_args(argv)
    cfg = TrainConfig(
        data_dir=args.data_dir, output=args.output, epochs=args.epochs,
        batch_size=args.batch_size, lr=args.lr, device=args.device, tiny=args.tiny,
    )
    train(cfg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
