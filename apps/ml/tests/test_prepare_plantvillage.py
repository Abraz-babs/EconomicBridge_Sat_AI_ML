"""Tests for scripts/prepare_plantvillage.py (Slice 20).

Builds a synthetic PlantVillage source tree of empty .jpg files in a
tmp dir — no real images or torch needed — and exercises the
reorganisation logic: copy, combine-multiple-sources, dedup on re-run,
missing-source warnings, dry-run, and the CROP_CLASSES guard.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from models.crop_classifier import CROP_CLASSES
from scripts.prepare_plantvillage import (
    PLANTVILLAGE_CLASS_MAP,
    prepare,
)


def _make_source(root: Path, layout: dict[str, int]) -> None:
    """Create source folders each with N empty .jpg files."""
    for folder, n in layout.items():
        d = root / folder
        d.mkdir(parents=True, exist_ok=True)
        for i in range(n):
            (d / f"img_{i}.jpg").write_bytes(b"")


# ─── Class map integrity ───────────────────────────────────────────────────


def test_class_map_targets_are_all_real_crop_classes():
    assert set(PLANTVILLAGE_CLASS_MAP) <= set(CROP_CLASSES)


def test_class_map_only_covers_maize_and_tomato():
    """PlantVillage has no cassava/rice/plantain — those come from Kaggle.
    Guard against someone adding an unsourceable mapping here."""
    for target in PLANTVILLAGE_CLASS_MAP:
        assert target.startswith(("maize_", "tomato_")), target


# ─── Reorganisation behaviour ──────────────────────────────────────────────


def test_prepare_copies_single_source_class(tmp_path):
    src = tmp_path / "pv"
    dest = tmp_path / "out"
    _make_source(src, {"Corn_(maize)___healthy": 5})

    result = prepare(
        source_root=src, dest_root=dest,
        class_map={"maize_healthy": ["Corn_(maize)___healthy"]},
    )

    assert result.total_copied == 5
    placed = list((dest / "maize_healthy").glob("*.jpg"))
    assert len(placed) == 5


def test_prepare_combines_multiple_sources_into_one_target(tmp_path):
    src = tmp_path / "pv"
    dest = tmp_path / "out"
    _make_source(src, {
        "Corn_(maize)___Cercospora_leaf_spot Gray_leaf_spot": 3,
        "Corn_(maize)___Common_rust_": 4,
    })

    result = prepare(
        source_root=src, dest_root=dest,
        class_map={"maize_streak_virus": [
            "Corn_(maize)___Cercospora_leaf_spot Gray_leaf_spot",
            "Corn_(maize)___Common_rust_",
        ]},
    )

    assert result.total_copied == 7
    placed = list((dest / "maize_streak_virus").glob("*.jpg"))
    assert len(placed) == 7


def test_prepare_dedup_filename_collision_across_sources(tmp_path):
    """Both source folders have img_0.jpg — the source-folder prefix must
    keep them from clobbering each other."""
    src = tmp_path / "pv"
    dest = tmp_path / "out"
    _make_source(src, {"Corn_(maize)___Common_rust_": 1})
    # second folder with an identically-named file
    (src / "Corn_(maize)___Northern_Leaf_Blight").mkdir(parents=True)
    (src / "Corn_(maize)___Northern_Leaf_Blight" / "img_0.jpg").write_bytes(b"")

    result = prepare(
        source_root=src, dest_root=dest,
        class_map={"maize_streak_virus": [
            "Corn_(maize)___Common_rust_",
            "Corn_(maize)___Northern_Leaf_Blight",
        ]},
    )
    assert result.total_copied == 2
    assert len(list((dest / "maize_streak_virus").glob("*.jpg"))) == 2


def test_prepare_is_idempotent_on_rerun(tmp_path):
    src = tmp_path / "pv"
    dest = tmp_path / "out"
    _make_source(src, {"Tomato___healthy": 6})
    cmap = {"tomato_healthy": ["Tomato___healthy"]}

    first = prepare(source_root=src, dest_root=dest, class_map=cmap)
    assert first.total_copied == 6

    second = prepare(source_root=src, dest_root=dest, class_map=cmap)
    assert second.total_copied == 0
    assert second.total_skipped == 6


def test_prepare_warns_on_missing_source(tmp_path):
    src = tmp_path / "pv"
    dest = tmp_path / "out"
    src.mkdir()
    # No source folders created at all.
    result = prepare(
        source_root=src, dest_root=dest,
        class_map={"maize_healthy": ["Corn_(maize)___healthy"]},
    )
    assert result.total_copied == 0
    assert result.classes[0].missing_sources == ["Corn_(maize)___healthy"]


def test_prepare_dry_run_writes_nothing(tmp_path):
    src = tmp_path / "pv"
    dest = tmp_path / "out"
    _make_source(src, {"Tomato___Late_blight": 4})

    result = prepare(
        source_root=src, dest_root=dest, dry_run=True,
        class_map={"tomato_late_blight": ["Tomato___Late_blight"]},
    )
    assert result.total_copied == 4          # counts what it WOULD copy
    assert not dest.exists()                  # but writes nothing


def test_prepare_only_picks_image_extensions(tmp_path):
    src = tmp_path / "pv"
    dest = tmp_path / "out"
    d = src / "Tomato___healthy"
    d.mkdir(parents=True)
    (d / "leaf.jpg").write_bytes(b"")
    (d / "notes.txt").write_bytes(b"")
    (d / "thumbs.db").write_bytes(b"")

    result = prepare(
        source_root=src, dest_root=dest,
        class_map={"tomato_healthy": ["Tomato___healthy"]},
    )
    assert result.total_copied == 1


def test_prepare_rejects_target_not_in_crop_classes(tmp_path):
    src = tmp_path / "pv"
    dest = tmp_path / "out"
    src.mkdir()
    with pytest.raises(ValueError, match="not in CROP_CLASSES"):
        prepare(
            source_root=src, dest_root=dest,
            class_map={"banana_split": ["Whatever"]},
        )
