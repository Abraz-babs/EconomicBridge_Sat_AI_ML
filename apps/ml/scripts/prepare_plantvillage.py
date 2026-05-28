"""PlantVillage → CropGuard dataset-prep CLI (Slice 20).

Automates step 2b of docs/CROPGUARD_TRAINING.md: reorganising a raw
PlantVillage download into the 12-class ImageFolder layout the trainer
(scripts/train_crop_classifier.py) expects.

PlantVillage only covers the maize + tomato families — 4 of our 12
CROP_CLASSES. The cassava / rice / plantain classes come from separate
Kaggle datasets (see the training guide); this script handles the
PlantVillage subset and leaves the rest for the operator to drop in.

Usage (operator-run, after downloading PlantVillage):

    # Copy the relevant classes into /data/cropguard/
    python apps/ml/scripts/prepare_plantvillage.py \\
        --source /downloads/PlantVillage-Dataset/raw/color \\
        --dest   /data/cropguard

    # Preview what would happen without writing anything
    python apps/ml/scripts/prepare_plantvillage.py \\
        --source /downloads/PlantVillage-Dataset/raw/color \\
        --dest   /data/cropguard --dry-run

    # Hardlink instead of copy (saves disk on the same volume)
    python apps/ml/scripts/prepare_plantvillage.py \\
        --source ... --dest ... --link hardlink

The script is intentionally conservative: it never deletes anything in
`dest`, only adds. Re-running is safe — files already present are
skipped. Source folders missing from the download are warned about,
not fatal, so a partial PlantVillage mirror still works.
"""
from __future__ import annotations

import argparse
import logging
import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

ML_ROOT = Path(__file__).resolve().parent.parent
if str(ML_ROOT) not in sys.path:
    sys.path.insert(0, str(ML_ROOT))

from models.crop_classifier import CROP_CLASSES  # noqa: E402

log = logging.getLogger("plantvillage_prep")


# Maps each of OUR class folders to the PlantVillage source folder(s)
# that populate it. A list means "combine these source folders into the
# one target". Only the maize + tomato families exist in PlantVillage —
# the other six CROP_CLASSES are sourced from Kaggle and intentionally
# absent here (the trainer skips empty class folders with a warning).
#
# PlantVillage uses the "color" variant folder names (Crop___Condition).
PLANTVILLAGE_CLASS_MAP: dict[str, list[str]] = {
    "maize_healthy": ["Corn_(maize)___healthy"],
    # PlantVillage has no dedicated maize-streak-virus class. Northern
    # Leaf Blight is mapped to its own target; the remaining two foliar
    # diseases (Cercospora gray leaf spot + Common rust) are the closest
    # visual proxies for the streak-virus target until dedicated MSV
    # images are sourced. Documented in CROPGUARD_TRAINING.md §2b.
    "maize_streak_virus": [
        "Corn_(maize)___Cercospora_leaf_spot Gray_leaf_spot",
        "Corn_(maize)___Common_rust_",
    ],
    "maize_northern_blight": ["Corn_(maize)___Northern_Leaf_Blight"],
    "tomato_healthy": ["Tomato___healthy"],
    "tomato_late_blight": ["Tomato___Late_blight"],
}

# Image extensions PlantVillage ships. Lower-cased compare.
_IMAGE_EXTS = {".jpg", ".jpeg", ".png"}

LinkMode = str  # "copy" | "symlink" | "hardlink"


@dataclass(slots=True)
class ClassResult:
    target_class: str
    copied: int = 0
    skipped_existing: int = 0
    missing_sources: list[str] = field(default_factory=list)


@dataclass(slots=True)
class PrepResult:
    classes: list[ClassResult] = field(default_factory=list)
    dry_run: bool = False

    @property
    def total_copied(self) -> int:
        return sum(c.copied for c in self.classes)

    @property
    def total_skipped(self) -> int:
        return sum(c.skipped_existing for c in self.classes)


def _iter_images(folder: Path):
    """Yield image files (one level deep) in a source folder."""
    for entry in sorted(folder.iterdir()):
        if entry.is_file() and entry.suffix.lower() in _IMAGE_EXTS:
            yield entry


def _place(src: Path, dst: Path, mode: LinkMode) -> None:
    """Copy / symlink / hardlink one file. Caller ensures dst's parent
    exists and dst does not already exist."""
    if mode == "symlink":
        os.symlink(src, dst)
    elif mode == "hardlink":
        os.link(src, dst)
    else:  # copy
        shutil.copy2(src, dst)


def prepare(
    *,
    source_root: Path,
    dest_root: Path,
    link_mode: LinkMode = "copy",
    dry_run: bool = False,
    class_map: dict[str, list[str]] | None = None,
) -> PrepResult:
    """Reorganise a raw PlantVillage tree into the CropGuard layout.

    Returns a PrepResult with per-class counts. Never deletes; only
    adds files not already present in `dest_root`.
    """
    cmap = class_map if class_map is not None else PLANTVILLAGE_CLASS_MAP
    # Guard: every target class must be a real CROP_CLASSES entry so a
    # typo in the map can't silently create an unusable folder.
    unknown = set(cmap) - set(CROP_CLASSES)
    if unknown:
        raise ValueError(
            f"class_map targets not in CROP_CLASSES: {sorted(unknown)}"
        )

    result = PrepResult(dry_run=dry_run)
    for target_class, source_folders in cmap.items():
        cr = ClassResult(target_class=target_class)
        dest_dir = dest_root / target_class
        for sub in source_folders:
            src_dir = source_root / sub
            if not src_dir.is_dir():
                cr.missing_sources.append(sub)
                log.warning(
                    "source folder missing for %s: %s", target_class, sub
                )
                continue
            for img in _iter_images(src_dir):
                # Prefix with the source-folder slug so two source folders
                # combined into one target can't collide on identical
                # filenames (PlantVillage restarts numbering per folder).
                dst_name = f"{sub[:24].replace(' ', '_')}__{img.name}"
                dst = dest_dir / dst_name
                if dst.exists():
                    cr.skipped_existing += 1
                    continue
                if not dry_run:
                    dest_dir.mkdir(parents=True, exist_ok=True)
                    _place(img, dst, link_mode)
                cr.copied += 1
        result.classes.append(cr)
    return result


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    p.add_argument("--source", required=True, type=Path,
                   help="Raw PlantVillage folder (the one with Corn___* subdirs).")
    p.add_argument("--dest", required=True, type=Path,
                   help="CropGuard data dir to populate (created if absent).")
    p.add_argument("--link", default="copy",
                   choices=["copy", "symlink", "hardlink"],
                   help="How to place files. Default copy.")
    p.add_argument("--dry-run", action="store_true",
                   help="Report counts without writing anything.")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    args = _parse_args(argv)

    if not args.source.is_dir():
        log.error("source dir does not exist: %s", args.source)
        return 2

    result = prepare(
        source_root=args.source,
        dest_root=args.dest,
        link_mode=args.link,
        dry_run=args.dry_run,
    )

    prefix = "[dry-run] would place" if result.dry_run else "placed"
    for cr in result.classes:
        miss = f" (missing: {', '.join(cr.missing_sources)})" if cr.missing_sources else ""
        log.info(
            "%s %d → %s (%d already present)%s",
            prefix, cr.copied, cr.target_class, cr.skipped_existing, miss,
        )
    log.info(
        "%s %d images across %d PlantVillage-derived classes. "
        "Remaining CROP_CLASSES (cassava/rice/plantain) come from Kaggle "
        "— see docs/CROPGUARD_TRAINING.md.",
        prefix, result.total_copied, len(result.classes),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
