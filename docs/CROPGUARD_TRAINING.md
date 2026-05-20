# CropGuard ResNet-50 — Training Guide

Step-by-step runbook for producing `apps/ml/artifacts/crop_classifier.pth`,
the artifact that unlocks `trained` mode for the CropGuard classifier.

The ML service expects this file at the path above; when present,
`CropClassifier._load()` (in [`apps/ml/models/crop_classifier.py`](../apps/ml/models/crop_classifier.py))
switches execution mode from `untuned` → `trained` and `requires_human_review`
stops being hard-True on every call.

The training pipeline ships in [`apps/ml/scripts/`](../apps/ml/scripts/).
The CLI entry is `train_crop_classifier.py`; the library is `crop_training.py`.

---

## 1. Quick dev artifact (synthetic, 15 seconds)

For dashboard demos and "does trained mode work?" checks. Produces a
real `.pth` from a tiny synthetic dataset — predictions will be useless
but the integration is exercised end-to-end.

```powershell
cd apps\ml
$env:CROPGUARD_PRODUCE_DEV_PTH = "1"
python -m pytest tests\test_crop_trainer.py::test_dev_artifact_smoke_train -m slow -s
Remove-Item Env:CROPGUARD_PRODUCE_DEV_PTH
```

The artifact lands at `apps/ml/artifacts/crop_classifier.pth` (~91 MB).
The file is `.gitignore`d — regenerate locally on each machine.

---

## 2. Real PlantVillage training

PlantVillage covers a subset of our 12 classes — specifically the maize
and tomato families. The other crops (cassava, rice, plantain) need
supplementary datasets sourced separately.

### 2a. Source the data

| Crop | Dataset | URL | Notes |
|------|---------|-----|-------|
| Maize, Tomato | PlantVillage | https://github.com/spMohanty/PlantVillage-Dataset | ~2 GB; 38 classes total, we use 6 |
| Cassava | Cassava Leaf Disease (Kaggle) | https://www.kaggle.com/c/cassava-leaf-disease-classification | Requires Kaggle account |
| Rice | Rice Leaf Diseases (Kaggle) | https://www.kaggle.com/datasets/vbookshelf/rice-leaf-diseases | ~120 MB |
| Plantain | Banana Disease Recognition (Kaggle) | https://www.kaggle.com/datasets/sujaykapadnis/banana-disease-recognition-dataset | Plantain ≈ Banana for our purposes |

### 2b. Map raw class names to ours

Our model output is fixed to 12 classes in this order
(`models.crop_classifier.CROP_CLASSES`):

```
cassava_healthy, cassava_mosaic_disease, cassava_brown_streak,
maize_healthy, maize_streak_virus, maize_northern_blight,
rice_healthy, rice_blast,
tomato_healthy, tomato_late_blight,
plantain_healthy, plantain_black_sigatoka,
```

Reorganise the downloaded data into this layout:

```
/data/cropguard/
├── cassava_healthy/                ← Kaggle cassava: "Healthy"
├── cassava_mosaic_disease/         ← Kaggle cassava: "CMD"
├── cassava_brown_streak/           ← Kaggle cassava: "CBSD"
├── maize_healthy/                  ← PlantVillage: Corn___healthy
├── maize_streak_virus/             ← (combine PlantVillage Cercospora_leaf_spot
│                                      + Common_rust as approximation, or
│                                      source dedicated MSV images)
├── maize_northern_blight/          ← PlantVillage: Corn___Northern_Leaf_Blight
├── rice_healthy/                   ← Kaggle rice: "Healthy"
├── rice_blast/                     ← Kaggle rice: "Leaf blast"
├── tomato_healthy/                 ← PlantVillage: Tomato___healthy
├── tomato_late_blight/             ← PlantVillage: Tomato___Late_blight
├── plantain_healthy/               ← Kaggle banana: "Healthy"
└── plantain_black_sigatoka/        ← Kaggle banana: "Sigatoka"
```

The trainer enforces this layout: any subfolder name **not** in
`CROP_CLASSES` will fail with `ValueError: Folder class names not in
CROP_CLASSES`. Missing or empty class folders are skipped with a warning.

### 2c. Train

```powershell
cd <repo>
python apps/ml/scripts/train_crop_classifier.py `
    --data-dir /data/cropguard `
    --epochs 10 `
    --batch-size 32 `
    --learning-rate 1e-3 `
    --val-fraction 0.2 `
    --num-workers 4
```

Expected wall-clock:

| Hardware | Time per epoch | Total (10 epochs) |
|----------|---------------|-------------------|
| CPU (laptop) | 25–40 min | 4–7 h |
| Single NVIDIA T4 / 4070 | 1–2 min | 10–20 min |
| Single A100 | <1 min | ~5 min |

Add `--unfreeze-backbone` to fine-tune the full ResNet-50 (~3x slower,
modest accuracy boost on the harder classes).

### 2d. Verify

After training:

```powershell
# 1. File exists at the expected path
ls apps\ml\artifacts\crop_classifier.pth

# 2. Start the ML service — logs should say "loading weights from ..."
cd apps\ml
python -m uvicorn main:app --port 8002

# 3. Hit the endpoint with a real image
$body = @{
  tenant_id = "kebbi"
  image_base64 = [Convert]::ToBase64String([IO.File]::ReadAllBytes("test.jpg"))
  persist = $false
} | ConvertTo-Json
Invoke-RestMethod -Uri http://localhost:8002/api/v1/predict/crop_disease `
  -Method Post -Body $body -ContentType "application/json"
```

The response's `model_version` should now end in `-trained`. If it
still says `-untuned` or `-stub`, check the ML service logs — it
fell back because something went wrong loading the .pth.

---

## 3. Hyperparameters that matter

- `--epochs`: 10 is a reasonable default for transfer learning on
  ~5K images per class. More if you unfreeze the backbone; fewer if
  validation loss flattens early.
- `--batch-size`: 32 is the GPU sweet spot for ResNet-50 at 224×224.
  Drop to 16 if you OOM, raise to 64+ if you have an A100.
- `--learning-rate`: 1e-3 works for the frozen-backbone (head-only)
  case. Drop to 1e-4 with `--unfreeze-backbone` to avoid destroying
  the pretrained weights.
- `--val-fraction`: 0.2 (the default) gives an honest 80/20 split.
  Production training should use a properly held-out test set; this
  flag isn't designed for that.

---

## 4. Class list breaking-change protocol

`CROP_CLASSES` order **is the model output index**. If you need to add
or reorder classes:

1. Bump `MODEL_NAME` *minor* version in `crop_classifier.py` (e.g.
   "crop_classifier_v2") — old artifacts trained against the previous
   class list MUST NOT load against the new one.
2. Retrain from scratch — partial loads via `strict=False` will silently
   misalign labels and emit garbage predictions.
3. Update the dashboard's class-label rendering.

The classifier's `model_version` string (`0.1.0-trained` /
`0.1.0-untuned` / `0.1.0-stub`) is the cheap canary: every prediction
carries it through to the audit log, so a class-list mismatch surfaces
as a flood of suddenly-different version strings on the dashboard.
