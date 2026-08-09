"""Fold CCMT field imagery into the CropGuard training set, and make the
validation split FIELD-ONLY so the headline number means something.

## Why

The classifier answers cassava for almost any field photograph. The cause is in
how the training set was assembled, not in the code: maize and tomato came from
PlantVillage (laboratory — one detached leaf, plain background), cassava, rice
and plantain from field-collected sets. Photographic STYLE therefore predicts
the crop before a single leaf is examined, and the network learned that
shortcut. Published result for the same setup: a fine-tuned ResNet-50 loses 67.7
points transferring PlantVillage -> in-field imagery.

CCMT (Mendeley `bwh3zbpkpv`, CC BY 4.0, attribution required) is 24,881 images
photographed on farms in GHANA — one of our own pilot regions — and validated by
plant virologists. Adding it gives maize and tomato field examples for the first
time, so "looks like a field photo" stops implying "is cassava".

## Two decisions worth understanding before changing this file

**RAW images only.** The download also ships 102,976 author-augmented images.
Training on those would put augmented variants of the SAME original photo into
both train and validation, and the resulting accuracy would measure memorisation
of a photo we already trained on.

**Validation is field-only.** The old trainer took a random split of one pooled
set, so validation looked exactly like training and 0.872 measured in-domain
memorisation — it said nothing about a field photo. Here the validation split is
drawn only from CCMT field imagery, so the number reported is the number we
actually care about, and it will start out much worse than 0.872. That is the
point.

## Mapping

Only classes where the CROP and the DISEASE both match ours are mapped. A wrong
label is worse than a missing class:

* CCMT cassava "brown spot" is NOT our `cassava_brown_streak` (CBSD) — a
  different disease. Never conflate them.
* CCMT tomato "leaf blight" is commonly EARLY blight (Alternaria); our class is
  `tomato_late_blight` (Phytophthora). Not mapped.
* CCMT maize "leaf blight" is probably northern corn leaf blight (Exserohilum
  turcicum), the dominant maize leaf blight in West Africa — but "probably" is
  not good enough for a training label, so it is behind MAP_MAIZE_LEAF_BLIGHT
  and defaults OFF pending an agronomic confirmation.

Usage:
    python apps/ml/scripts/prepare_ccmt.py --out data/cropguard_v2
"""
from __future__ import annotations

import argparse
import json
import random
import shutil
from pathlib import Path

# Set True only when an agronomist confirms CCMT "leaf blight" (maize) is
# northern corn leaf blight. See module docstring.
MAP_MAIZE_LEAF_BLIGHT = False

CCMT_ROOT = Path(
    "apps/ml/.kaggle_src/ccmt/Dataset for Crop Pest and Disease Detection"
    "/Raw Data/CCMT Dataset"
)
LAB_ROOT = Path("data/cropguard")          # the existing (mostly lab) set

# (crop folder, CCMT class folder) -> our canonical class
CCMT_MAP: dict[tuple[str, str], str] = {
    ("Cassava", "healthy"):      "cassava_healthy",
    ("Cassava", "mosaic"):       "cassava_mosaic_disease",
    ("Maize",   "healthy"):      "maize_healthy",
    ("Maize",   "streak virus"): "maize_streak_virus",
    ("Tomato",  "healthy"):      "tomato_healthy",
}
if MAP_MAIZE_LEAF_BLIGHT:
    CCMT_MAP[("Maize", "leaf blight")] = "maize_northern_blight"

# Fraction of CCMT field images held out for validation. Held out by IMAGE;
# the raw set has no augmented siblings, so there is nothing to leak.
VAL_FRACTION = 0.20
SEED = 20260809
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".JPG", ".JPEG", ".PNG"}


def _images(folder: Path) -> list[Path]:
    return sorted(p for p in folder.rglob("*") if p.suffix in IMAGE_SUFFIXES)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/cropguard_v2")
    ap.add_argument("--link", action="store_true",
                    help="hardlink instead of copy (same volume only)")
    args = ap.parse_args()

    out = Path(args.out)
    if not CCMT_ROOT.exists():
        print(f"CCMT not found at {CCMT_ROOT}")
        return 1

    rng = random.Random(SEED)
    manifest: dict[str, dict] = {}
    counts: dict[str, dict[str, int]] = {}

    def place(src: Path, split: str, cls: str, source: str, idx: int) -> None:
        dst_dir = out / split / cls
        dst_dir.mkdir(parents=True, exist_ok=True)
        dst = dst_dir / f"{source}_{idx:06d}{src.suffix.lower()}"
        if dst.exists():
            return
        if args.link:
            try:
                dst.hardlink_to(src)
                return
            except OSError:
                pass
        shutil.copy2(src, dst)

    # ── CCMT field imagery: train portion + the ENTIRE validation split ──
    for (crop, ccmt_cls), canonical in sorted(CCMT_MAP.items()):
        src_dir = CCMT_ROOT / crop / ccmt_cls
        if not src_dir.is_dir():
            print(f"  MISSING {src_dir}")
            continue
        imgs = _images(src_dir)
        rng.shuffle(imgs)
        n_val = int(len(imgs) * VAL_FRACTION)
        for i, p in enumerate(imgs[:n_val]):
            place(p, "val_field", canonical, "ccmt", i)
        for i, p in enumerate(imgs[n_val:]):
            place(p, "train", canonical, "ccmt", i)
        counts.setdefault(canonical, {})["ccmt_train"] = len(imgs) - n_val
        counts[canonical]["ccmt_val"] = n_val
        print(f"  {crop}/{ccmt_cls:14} -> {canonical:24} "
              f"{len(imgs) - n_val} train / {n_val} val")

    # ── the existing set: TRAIN ONLY. It is mostly laboratory imagery, and
    #    validating on it is what produced a meaningless 0.872. ──
    if LAB_ROOT.exists():
        for cls_dir in sorted(p for p in LAB_ROOT.iterdir() if p.is_dir()):
            imgs = _images(cls_dir)
            for i, p in enumerate(imgs):
                place(p, "train", cls_dir.name, "existing", i)
            counts.setdefault(cls_dir.name, {})["existing_train"] = len(imgs)
    else:
        print(f"  NOTE: {LAB_ROOT} absent — CCMT only")

    manifest = {
        "seed": SEED,
        "val_fraction": VAL_FRACTION,
        "maize_leaf_blight_mapped": MAP_MAIZE_LEAF_BLIGHT,
        "validation_note":
            "val_field contains CCMT FIELD imagery only. Accuracy here is field "
            "accuracy. It is not comparable to the old 0.872, which was a random "
            "split of laboratory images.",
        "attribution":
            "CCMT dataset, Mendeley bwh3zbpkpv, CC BY 4.0 — Mensah et al., "
            "'CCMT: Dataset for crop pest and disease detection', Data in Brief.",
        "counts": counts,
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print("\nper-class totals:")
    for cls in sorted(counts):
        c = counts[cls]
        print(f"  {cls:26} train={c.get('ccmt_train',0)+c.get('existing_train',0):5} "
              f"(field {c.get('ccmt_train',0)}, lab {c.get('existing_train',0)})"
              f"  val_field={c.get('ccmt_val',0)}")
    print(f"\nwrote {out/'manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
