"""Judge the retrained classifier on the tests that can embarrass it.

The training run reports accuracy on held-out CCMT images. That is a real
number, but it is held out BY IMAGE from a single corpus — same cameras, same
farms, same season — so it answers "does it recognise CCMT-style field photos",
not "does it read a leaf". A model that had merely swapped one shortcut for a
CCMT-specific one would score well there and remain useless in Kebbi.

So this evaluates three things separately and refuses to average them:

1. **CCMT held-out, per class.** Where the aggregate comes from, and whether it
   is carried by one easy class.
2. **Independent field photographs** — Wikimedia maize, no relationship to
   CCMT: different cameras, continent, season. THIS is the number to quote.
3. **Laboratory imagery** — the old model scored 12/12 here. A retrain that
   fixes the field and breaks the lab has traded one failure for another.

Also reports the DECLARED-CROP MASS distribution, because MIN_CROP_MASS (0.50)
was calibrated against the old weights and the band will have moved.

    python apps/ml/scripts/eval_crop_v2.py --weights apps/ml/artifacts/crop_classifier_v2.pth
"""
from __future__ import annotations

import argparse
import collections
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models.crop_classifier import CROP_CLASSES, crop_of  # noqa: E402

SCRATCH = Path(
    r"C:/Users/HP/AppData/Local/Temp/claude"
    r"/c--Users-HP-Downloads-economicbridge-ide-starter"
    r"/9b05201c-4841-4d99-81fd-e9e1f1cd6d2f/scratchpad"
)
VAL_DIR = Path("data/cropguard_v2/val_field")
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}


def load_model(weights: Path):
    import torch
    from torchvision import models

    model = models.resnet50(weights=None)
    model.fc = torch.nn.Linear(model.fc.in_features, len(CROP_CLASSES))
    model.load_state_dict(torch.load(weights, map_location="cpu"))
    model.eval()
    return model


def transform():
    from torchvision import transforms
    return transforms.Compose([
        transforms.Resize(256),
        transforms.CenterCrop(224),
        transforms.ToTensor(),
        transforms.Normalize(mean=[0.485, 0.456, 0.406],
                             std=[0.229, 0.224, 0.225]),
    ])


def predict(model, tf, path: Path):
    import torch
    from PIL import Image
    with Image.open(path) as im:
        x = tf(im.convert("RGB")).unsqueeze(0)
    with torch.no_grad():
        p = torch.softmax(model(x), dim=1).squeeze(0).tolist()
    top = max(range(len(p)), key=lambda i: p[i])
    return CROP_CLASSES[top], p


def crop_mass(probs: list[float], crop: str) -> float:
    return sum(v for c, v in zip(CROP_CLASSES, probs) if crop_of(c) == crop)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", type=Path,
                    default=Path("apps/ml/artifacts/crop_classifier_v2.pth"))
    ap.add_argument("--limit-per-class", type=int, default=60,
                    help="cap CCMT images per class (CPU inference is slow)")
    args = ap.parse_args()

    if not args.weights.exists():
        print(f"weights not found: {args.weights}")
        return 1
    model, tf = load_model(args.weights), transform()
    print(f"weights: {args.weights}\n")

    # ── 1. CCMT held-out, per class ──────────────────────────────────────
    print("=== CCMT held-out field imagery, per class ===")
    print("    (same corpus as training — recognition, not generalisation)")
    overall_ok = overall_n = 0
    if VAL_DIR.exists():
        for cls_dir in sorted(p for p in VAL_DIR.iterdir() if p.is_dir()):
            imgs = [p for p in sorted(cls_dir.rglob("*"))
                    if p.suffix.lower() in IMAGE_SUFFIXES][:args.limit_per_class]
            ok = sum(1 for p in imgs if predict(model, tf, p)[0] == cls_dir.name)
            overall_ok += ok
            overall_n += len(imgs)
            pct = ok / len(imgs) if imgs else 0.0
            print(f"  {cls_dir.name:26} {ok:3}/{len(imgs):3}  {pct:6.1%}")
        if overall_n:
            print(f"  {'SAMPLED TOTAL':26} {overall_ok:3}/{overall_n:3}  "
                  f"{overall_ok / overall_n:6.1%}")
    else:
        print(f"  {VAL_DIR} missing")

    # ── 2. independent field photographs — the honest test ───────────────
    print("\n=== INDEPENDENT field photographs (Wikimedia maize) ===")
    print("    different cameras/continent/season — no link to CCMT")
    field = sorted((SCRATCH / "fieldimgs").glob("*.jpg"))
    for p in field:
        cls, probs = predict(model, tf, p)
        m = crop_mass(probs, "maize")
        verdict = "MAIZE" if crop_of(cls) == "maize" else "wrong crop"
        print(f"  {p.name:24} -> {cls:26} maize-mass={m:6.1%}  {verdict}")
    if field:
        right = sum(1 for p in field if crop_of(predict(model, tf, p)[0]) == "maize")
        print(f"  correct CROP on {right}/{len(field)}  (old model: 0/3)")

    # ── 3. laboratory imagery — did we break what worked? ────────────────
    print("\n=== Laboratory imagery (old model scored 12/12) ===")
    lab = sorted((SCRATCH / "testimgs").glob("*.jpg"))
    ok = 0
    for p in lab:
        expected = p.stem.split("__")[0]
        cls, _ = predict(model, tf, p)
        ok += cls == expected
        flag = "" if cls == expected else f"   <- expected {expected}"
        print(f"  {p.name:32} -> {cls}{flag}")
    if lab:
        print(f"  {ok}/{len(lab)} correct")

    # ── 4. where MIN_CROP_MASS should now sit ────────────────────────────
    print("\n=== declared-crop mass (MIN_CROP_MASS recalibration) ===")
    buckets: dict[str, list[float]] = collections.defaultdict(list)
    for p in lab:
        buckets["lab"].append(crop_mass(predict(model, tf, p)[1],
                                        crop_of(p.stem.split("__")[0])))
    for p in field:
        buckets["field(independent)"].append(
            crop_mass(predict(model, tf, p)[1], "maize"))
    for k, v in buckets.items():
        if v:
            print(f"  {k:22} min={min(v):.4f}  max={max(v):.4f}  n={len(v)}")
    print("\n  MIN_CROP_MASS is 0.50, calibrated on the OLD weights "
          "(lab 0.86-0.9996, field 0.0094-0.1699).")
    print("  If the bands above overlap, the crop-mass guard no longer "
          "separates the two and must be re-derived or retired.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
