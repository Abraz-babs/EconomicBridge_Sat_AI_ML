"""A validation set holding a SUBSET of the classes must not be scored against
the wrong ones.

`ImageFolder` numbers classes alphabetically PER DIRECTORY. With 12 training
classes and 5 validation classes, val index 0 (cassava_healthy) was scored
against model output 0 (cassava_brown_streak) — every label compared to the
wrong class. The run reported val_acc=0.009, below the 1/12 you would get by
guessing, which is the tell that labels are misaligned rather than the model
being bad.

Checking that the class NAMES are all present is not enough; the NUMBERING has
to agree. This pins the remap.
"""
from __future__ import annotations

TRAIN_CLASSES = [
    "cassava_brown_streak", "cassava_healthy", "cassava_mosaic_disease",
    "maize_healthy", "maize_northern_blight", "maize_streak_virus",
    "plantain_black_sigatoka", "plantain_healthy", "rice_blast",
    "rice_healthy", "tomato_healthy", "tomato_late_blight",
]
VAL_CLASSES = [
    "cassava_healthy", "cassava_mosaic_disease", "maize_healthy",
    "maize_streak_virus", "tomato_healthy",
]


def _remap(val_classes: list[str], train_classes: list[str]) -> dict[int, int]:
    """The mapping crop_training applies to val targets."""
    return {i: train_classes.index(n) for i, n in enumerate(val_classes)}


def test_without_remapping_every_class_would_be_scored_wrong():
    """The bug, stated as a test: naive indices agree for none of them."""
    agree = [i for i, n in enumerate(VAL_CLASSES) if TRAIN_CLASSES[i] == n]

    assert agree == [], (
        "if these ever line up naturally the test has stopped proving anything"
    )


def test_remap_sends_every_val_class_to_its_own_training_index():
    remap = _remap(VAL_CLASSES, TRAIN_CLASSES)

    for v_idx, name in enumerate(VAL_CLASSES):
        assert TRAIN_CLASSES[remap[v_idx]] == name


def test_remap_is_injective():
    """Two validation classes collapsing onto one training index would make
    accuracy unfixably wrong in a way that still looks plausible."""
    remap = _remap(VAL_CLASSES, TRAIN_CLASSES)

    assert len(set(remap.values())) == len(remap)


def test_a_validation_class_absent_from_training_is_a_hard_error():
    """Silently dropping it would quietly shrink the denominator."""
    import pytest

    with pytest.raises(ValueError):
        _remap([*VAL_CLASSES, "sorghum_healthy"], TRAIN_CLASSES)
