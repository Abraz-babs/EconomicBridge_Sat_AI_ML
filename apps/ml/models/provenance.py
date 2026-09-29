"""A model trained on generated data does not answer real questions.

The conflict predictor and the yield predictor ship only as
0.1.0-dev-synthetic artifacts: Random Forests fitted to generated data so the
pipeline could be built before real labels existed. A probability from them is
not evidence about a real place, so the service refuses to serve one
(2026-09-29, the operator's rule: anything fake becomes real). They answer
again once an artifact trained on real data replaces them - its version no
longer says "synthetic". The test suite opts in with SERVE_SYNTHETIC_MODELS.
"""
from __future__ import annotations

from fastapi import HTTPException, status

from config import get_settings


def require_real_model(model_name: str, model_version: str) -> None:
    """503 unless the model was trained on real data (or tests opted in)."""
    if "synthetic" in model_version.lower() and not get_settings().serve_synthetic_models:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "MODEL_NOT_TRAINED_ON_REAL_DATA",
                "message": (
                    f"The {model_name} ({model_version}) was trained on generated data, "
                    "so it does not serve predictions. It returns when a model trained "
                    "on real data replaces it."
                ),
            },
        )
