"""Field directions (services/places.py) — pure parts and the failure posture."""
from __future__ import annotations

import asyncio

from services.places import compass, nearest_places


def test_compass_points_from_the_village_to_the_alert():
    # Kurmin Kaya sits NW of the Ngaski patch, so the patch is SE of the village.
    assert compass(4.5540, 10.1090, 4.5605, 10.1023) == "SE"
    assert compass(0.0, 0.0, 0.0, 1.0) == "N"
    assert compass(0.0, 0.0, 1.0, 0.0) == "E"
    assert compass(0.0, 0.0, -1.0, -1.0) == "SW"


def test_no_located_alerts_means_no_query():
    class Untouchable:
        def begin_nested(self):  # pragma: no cover — must not be reached
            raise AssertionError("queried with nothing to look up")

    assert asyncio.run(nearest_places(Untouchable(), [])) == []
    assert asyncio.run(nearest_places(Untouchable(), [None, None])) == [None, None]


def test_a_failed_lookup_leaves_the_alerts_intact():
    """Directions are extra. A broken lookup must return 'unknown' for every
    alert rather than raise and take the alert list down with it."""
    class Broken:
        def begin_nested(self):
            raise RuntimeError("database unavailable")

    assert asyncio.run(nearest_places(Broken(), [(4.56, 10.10), None])) == [None, None]


def test_point_list_parsing_is_strict():
    import pytest
    from fastapi import HTTPException

    from routers.geo import MAX_POINTS, _parse_points

    assert _parse_points("4.5605,10.1023;3.8097,11.8606") == [(4.5605, 10.1023), (3.8097, 11.8606)]
    for bad in ("", "4.56", "x,y", "200,10", ";".join(["1,1"] * (MAX_POINTS + 1))):
        with pytest.raises(HTTPException):
            _parse_points(bad)
