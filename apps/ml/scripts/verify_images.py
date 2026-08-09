"""Quarantine unreadable images before training, and say how many there were.

Training died on `OSError: Truncated File Read` — CCMT contains some JPEGs with
incomplete data, which is ordinary for a large field-collected corpus.

The tempting one-line fix is `ImageFile.LOAD_TRUNCATED_IMAGES = True`, which
makes PIL return whatever bytes arrived and pad the rest. That trains the model
on half-decoded images without anyone knowing, and a corrupted image in the
FIELD VALIDATION set would quietly corrupt the one number this whole exercise
exists to produce. So instead: verify every file, move the bad ones aside, and
report the count.

Moved rather than deleted — they are still evidence of what the source contains.

    python apps/ml/scripts/verify_images.py data/cropguard_v2
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}


def readable(path: Path) -> bool:
    """True if PIL can fully decode the file, not merely open it.

    `Image.verify()` is not enough: it checks structure without decoding, and
    the truncated JPEGs here open fine and fail on read. `load()` forces the
    decode that the training loop would do.
    """
    from PIL import Image
    try:
        with Image.open(path) as im:
            im.convert("RGB").load()
        return True
    except Exception:
        return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("root", type=Path)
    ap.add_argument("--quarantine", type=Path, default=None)
    args = ap.parse_args()

    root: Path = args.root
    quarantine = args.quarantine or (root.parent / f"{root.name}_corrupt")

    files = [p for p in root.rglob("*") if p.suffix.lower() in IMAGE_SUFFIXES]
    print(f"checking {len(files)} images under {root} ...")

    bad: list[Path] = []
    for i, p in enumerate(files, 1):
        if not readable(p):
            bad.append(p)
        if i % 2000 == 0:
            print(f"  {i}/{len(files)} — {len(bad)} unreadable so far", flush=True)

    per_split: dict[str, int] = {}
    for p in bad:
        rel = p.relative_to(root)
        split = rel.parts[0] if len(rel.parts) > 1 else "?"
        cls = rel.parts[1] if len(rel.parts) > 2 else "?"
        per_split[f"{split}/{cls}"] = per_split.get(f"{split}/{cls}", 0) + 1
        dest = quarantine / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(p), str(dest))

    print(f"\nunreadable: {len(bad)} of {len(files)} "
          f"({len(bad) / max(len(files), 1):.3%})")
    for k in sorted(per_split):
        print(f"   {k:44} {per_split[k]}")
    if bad:
        print(f"moved to {quarantine}")
    # A high rate means the download itself is suspect, not just a few files.
    if len(bad) > len(files) * 0.02:
        print("\nWARNING: >2% unreadable — suspect the download, not the source.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
