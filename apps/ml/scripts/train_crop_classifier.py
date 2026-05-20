"""ResNet-50 crop disease classifier — training CLI (Slice 5b).

Operator-run. Trains a ResNet-50 transfer-learning head on a local
ImageFolder dataset and writes the state_dict to
`apps/ml/artifacts/crop_classifier.pth`, where `CropClassifier._load()`
picks it up automatically (turning execution mode from `untuned` →
`trained`).

Dataset layout expected (CLAUDE.md §11 — operator owns dataset prep):

  <data-dir>/
    cassava_healthy/
      *.jpg
    cassava_mosaic_disease/
      *.jpg
    ...

Subfolder names MUST match `models.crop_classifier.CROP_CLASSES`. The
operator maps PlantVillage class names to ours via the dataset-prep
guide (docs/CROPGUARD_TRAINING.md).

Run examples:

    # Real PlantVillage-derived dataset (after dataset prep)
    python apps/ml/scripts/train_crop_classifier.py \\
        --data-dir /data/cropguard --epochs 10 --batch-size 32

    # Smoke test on a synthetic toy dataset (used by tests)
    python apps/ml/scripts/train_crop_classifier.py \\
        --data-dir /tmp/toy --epochs 1 --batch-size 4 --tiny

Tiny mode caps steps per epoch and is the path the test suite uses
to produce a "dev" artifact from synthetic data.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Make `from config import ...` + sibling imports work when run from the repo root.
ML_ROOT = Path(__file__).resolve().parent.parent
if str(ML_ROOT) not in sys.path:
    sys.path.insert(0, str(ML_ROOT))

from scripts.crop_training import (  # noqa: E402
    DEFAULT_BATCH_SIZE,
    DEFAULT_EPOCHS,
    DEFAULT_LR,
    DEFAULT_SEED,
    DEFAULT_VAL_FRACTION,
    TrainConfig,
    train_model,
)


log = logging.getLogger("crop_trainer")


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="train_crop_classifier",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--data-dir", type=Path, required=True,
        help="Root ImageFolder dir. Subfolders = class names.",
    )
    p.add_argument(
        "--output", type=Path, default=None,
        help="Where to save the .pth (default: apps/ml/artifacts/crop_classifier.pth).",
    )
    p.add_argument("--epochs", type=int, default=DEFAULT_EPOCHS)
    p.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    p.add_argument("--learning-rate", type=float, default=DEFAULT_LR)
    p.add_argument(
        "--val-fraction", type=float, default=DEFAULT_VAL_FRACTION,
        help="Held-out fraction for validation (0..1).",
    )
    p.add_argument("--seed", type=int, default=DEFAULT_SEED)
    p.add_argument(
        "--unfreeze-backbone", action="store_true",
        help="Fine-tune all ResNet-50 weights, not just the FC head.",
    )
    p.add_argument("--num-workers", type=int, default=2)
    p.add_argument(
        "--tiny", action="store_true",
        help="Tiny mode: caps steps/epoch. Used for smoke tests + dev artifact.",
    )
    return p


def config_from_args(args: argparse.Namespace) -> TrainConfig:
    output = args.output
    if output is None:
        output = ML_ROOT / "artifacts" / "crop_classifier.pth"
    return TrainConfig(
        data_dir=args.data_dir,
        output_path=output,
        epochs=args.epochs,
        batch_size=args.batch_size,
        learning_rate=args.learning_rate,
        val_fraction=args.val_fraction,
        seed=args.seed,
        unfreeze_backbone=args.unfreeze_backbone,
        num_workers=args.num_workers,
        tiny=args.tiny,
    )


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    config = config_from_args(args)
    result = train_model(config)
    log.info(
        "done: samples=train:%d/val:%d val_acc=%.3f duration=%.1fs out=%s",
        result.train_samples, result.val_samples,
        result.final_val_accuracy, result.duration_seconds,
        result.output_path,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
