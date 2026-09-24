"""Village light: the classes, and people counted once at their nearest village."""
from __future__ import annotations

import numpy as np

from tasks.village_light_scan import UNLIT, assign_to_nearest, classify


def test_light_classes():
    assert classify(None) == "unknown"
    assert classify(0.0) == "unlit"
    assert classify(UNLIT - 0.01) == "unlit"
    assert classify(UNLIT) == "dim"
    assert classify(1.99) == "dim"
    assert classify(2.0) == "lit"


def test_town_quarters_never_double_count():
    """Two GRID3 points 0.4 km apart (quarters of one town) and a pixel between
    them: the pixel's people go to ONE of them, and the totals add up."""
    villages = np.array([[0.0, 0.0], [0.4, 0.0]])
    pixels = np.array([[0.1, 0.0], [0.3, 0.0], [0.2, 0.05]])
    people = np.array([100.0, 50.0, 30.0])
    totals, beyond = assign_to_nearest(pixels, people, villages, radius_km=1.0)
    assert totals.sum() == people.sum()
    assert beyond == 0.0
    assert totals[0] == 100.0 + 30.0 and totals[1] == 50.0


def test_people_beyond_the_radius_are_reported_not_forced_in():
    villages = np.array([[0.0, 0.0]])
    totals, beyond = assign_to_nearest(np.array([[0.5, 0.0], [5.0, 0.0]]),
                                       np.array([20.0, 999.0]), villages, radius_km=1.0)
    assert totals[0] == 20.0 and beyond == 999.0


def test_empty_inputs_are_safe():
    totals, beyond = assign_to_nearest(np.empty((0, 2)), np.array([]), np.array([[0.0, 0.0]]), 1.0)
    assert totals.tolist() == [0.0] and beyond == 0.0
