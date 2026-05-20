"""Training-loop library for the CropGuard ResNet-50 classifier.

Imported by `train_crop_classifier.py` (CLI) and `test_crop_trainer.py`
(tests). All heavy ML imports are local to function bodies so the
module is importable without torch installed.
"""
from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass
from pathlib import Path


log = logging.getLogger("crop_trainer")


DEFAULT_EPOCHS = 10
DEFAULT_BATCH_SIZE = 32
DEFAULT_LR = 1e-3
DEFAULT_VAL_FRACTION = 0.2
DEFAULT_SEED = 42
IMAGENET_MEAN = (0.485, 0.456, 0.406)
IMAGENET_STD = (0.229, 0.224, 0.225)


@dataclass(frozen=True, slots=True)
class TrainConfig:
    data_dir: Path
    output_path: Path
    epochs: int = DEFAULT_EPOCHS
    batch_size: int = DEFAULT_BATCH_SIZE
    learning_rate: float = DEFAULT_LR
    val_fraction: float = DEFAULT_VAL_FRACTION
    seed: int = DEFAULT_SEED
    unfreeze_backbone: bool = False
    num_workers: int = 2
    tiny: bool = False  # tiny mode = fewer steps + synthetic-OK


@dataclass(frozen=True, slots=True)
class TrainResult:
    output_path: Path
    train_samples: int
    val_samples: int
    classes_seen: list[str]
    final_train_loss: float
    final_val_accuracy: float
    epochs_completed: int
    duration_seconds: float


# ─── Dataset assembly ──────────────────────────────────────────────────────


def discover_class_dirs(data_dir: Path, expected: tuple[str, ...]) -> list[Path]:
    """Return one Path per expected class that exists AND has ≥1 image."""
    if not data_dir.exists():
        raise FileNotFoundError(f"data_dir does not exist: {data_dir}")

    found: list[Path] = []
    missing: list[str] = []
    empty: list[str] = []
    for class_name in expected:
        d = data_dir / class_name
        if not d.exists():
            missing.append(class_name)
            continue
        files = [p for p in d.iterdir() if p.is_file()]
        if not files:
            empty.append(class_name)
            continue
        found.append(d)

    if missing:
        log.warning("missing class dirs (will skip): %s", missing)
    if empty:
        log.warning("empty class dirs (will skip): %s", empty)
    if not found:
        raise RuntimeError(
            f"No usable class subfolders found under {data_dir}. "
            f"Expected at least one of: {list(expected)}"
        )
    return found


def build_class_remap(
    *, folder_classes: list[str], canonical: tuple[str, ...]
) -> dict[int, int]:
    """Map ImageFolder class index → canonical CROP_CLASSES index.

    Unknown folder names raise — the operator's dataset prep is meant
    to use exactly our class names, so an unknown name is a config bug
    we want to surface loudly rather than silently miscategorise."""
    canonical_index = {name: i for i, name in enumerate(canonical)}
    remap: dict[int, int] = {}
    unknown: list[str] = []
    for folder_idx, name in enumerate(folder_classes):
        if name not in canonical_index:
            unknown.append(name)
            continue
        remap[folder_idx] = canonical_index[name]
    if unknown:
        raise ValueError(
            f"Folder class names not in CROP_CLASSES: {unknown}. "
            f"Rename them or extend CROP_CLASSES."
        )
    return remap


def seed_everything(seed: int) -> None:
    """Deterministic seed across torch, numpy stdlib random, hash."""
    import torch
    import numpy as np

    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


# ─── Training loop ────────────────────────────────────────────────────────


def train_model(config: TrainConfig) -> TrainResult:
    """Run the training loop end-to-end. Returns the summary record.

    Standard transfer-learning recipe:
      * ImageNet-pretrained ResNet-50 backbone
      * Backbone frozen by default (unless config.unfreeze_backbone)
      * Fresh Linear(2048 → len(CROP_CLASSES)) head trained w/ CE
      * 224×224 crops, standard ImageNet normalisation
      * 80/20 train/val split (deterministic seed)
    """
    import torch
    from torch import nn, optim
    from torch.utils.data import DataLoader, random_split
    from torchvision import datasets, models, transforms

    from models.crop_classifier import CROP_CLASSES

    started = time.monotonic()

    seed_everything(config.seed)
    discover_class_dirs(config.data_dir, CROP_CLASSES)

    transform = transforms.Compose([
        transforms.Resize(256),
        transforms.CenterCrop(224),
        transforms.ToTensor(),
        transforms.Normalize(mean=list(IMAGENET_MEAN), std=list(IMAGENET_STD)),
    ])

    full = datasets.ImageFolder(str(config.data_dir), transform=transform)
    classes_seen = full.classes  # alphabetical, set by torchvision

    val_size = max(1, int(len(full) * config.val_fraction))
    train_size = len(full) - val_size
    if train_size <= 0:
        raise RuntimeError(
            f"Dataset too small: {len(full)} samples; can't split "
            f"into train ({train_size}) + val ({val_size})."
        )

    generator = torch.Generator().manual_seed(config.seed)
    train_set, val_set = random_split(
        full, [train_size, val_size], generator=generator,
    )
    train_loader = DataLoader(
        train_set, batch_size=config.batch_size, shuffle=True,
        num_workers=config.num_workers,
    )
    val_loader = DataLoader(
        val_set, batch_size=config.batch_size, shuffle=False,
        num_workers=config.num_workers,
    )

    device = torch.device("cpu")
    model = models.resnet50(weights=models.ResNet50_Weights.DEFAULT)
    if not config.unfreeze_backbone:
        for p in model.parameters():
            p.requires_grad = False
    # Output head matches the FULL canonical class list — even if the
    # training data only covers a subset, the model's output indices stay
    # aligned with CropClassifier's CROP_CLASSES so we can swap weights
    # in without changing the API contract.
    in_features = model.fc.in_features
    model.fc = nn.Linear(in_features, len(CROP_CLASSES))
    model = model.to(device)

    trainable = [p for p in model.parameters() if p.requires_grad]
    optimizer = optim.Adam(trainable, lr=config.learning_rate)
    loss_fn = nn.CrossEntropyLoss()

    folder_to_canonical = build_class_remap(
        folder_classes=classes_seen, canonical=CROP_CLASSES,
    )

    final_train_loss = 0.0
    final_val_acc = 0.0
    epochs_done = 0
    max_steps = 3 if config.tiny else None

    for epoch in range(1, config.epochs + 1):
        model.train()
        epoch_loss = 0.0
        steps = 0
        for inputs, labels in train_loader:
            if max_steps is not None and steps >= max_steps:
                break
            inputs = inputs.to(device)
            labels = torch.tensor(
                [folder_to_canonical[int(label)] for label in labels],
                device=device, dtype=torch.long,
            )
            optimizer.zero_grad()
            logits = model(inputs)
            loss = loss_fn(logits, labels)
            loss.backward()
            optimizer.step()
            epoch_loss += float(loss.item())
            steps += 1
        avg_loss = epoch_loss / max(steps, 1)
        final_train_loss = avg_loss

        model.eval()
        correct = 0
        total = 0
        with torch.no_grad():
            for inputs, labels in val_loader:
                inputs = inputs.to(device)
                labels = torch.tensor(
                    [folder_to_canonical[int(label)] for label in labels],
                    device=device, dtype=torch.long,
                )
                logits = model(inputs)
                preds = logits.argmax(dim=1)
                correct += int((preds == labels).sum().item())
                total += int(labels.size(0))
        val_acc = correct / max(total, 1)
        final_val_acc = val_acc
        epochs_done = epoch
        log.info(
            "epoch=%d/%d train_loss=%.4f val_acc=%.3f",
            epoch, config.epochs, avg_loss, val_acc,
        )

    config.output_path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(model.state_dict(), config.output_path)
    log.info("crop_classifier: wrote weights to %s", config.output_path)

    return TrainResult(
        output_path=config.output_path,
        train_samples=train_size,
        val_samples=val_size,
        classes_seen=list(classes_seen),
        final_train_loss=final_train_loss,
        final_val_accuracy=final_val_acc,
        epochs_completed=epochs_done,
        duration_seconds=time.monotonic() - started,
    )
