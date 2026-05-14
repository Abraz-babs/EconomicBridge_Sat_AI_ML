# Agent Skills — EconomicBridge
# ================================
# These are instructions for Claude Opus in agentic mode.
# When asked to perform one of these tasks, follow the skill exactly.
# Each skill generates ALL required files — not just the main file.

---

## SKILL: new-api-module
## Trigger: "create a new module for [X]" or "add [X] endpoint"

When creating a new API module, generate ALL of these files:

### 1. Router: apps/api/routers/{module_name}.py
```python
"""
{Module Name} router.

Handles HTTP endpoints for {description}.
All endpoints require authentication via JWT.
Tenant isolation enforced via TenantContext dependency.
"""
from uuid import UUID
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ..dependencies import get_current_user, get_db, get_tenant_context
from ..schemas.{module_name} import (
    {ModelName}Response,
    {ModelName}ListResponse,
    {ModelName}CreateRequest,
)
from ..services.{module_name} import {ModuleName}Service
from ..middleware.audit import audit_action
from ..models.user import User

router = APIRouter(prefix="/{module_name}", tags=["{Module Name}"])


@router.get("/", response_model={ModelName}ListResponse)
async def list_{items}(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    tenant_context=Depends(get_tenant_context),
) -> {ModelName}ListResponse:
    """
    List all {items} for the current tenant.

    Args:
        page: Page number (1-indexed).
        page_size: Number of items per page (max 100).
        db: Async database session.
        current_user: Authenticated user from JWT.
        tenant_context: Tenant isolation context.

    Returns:
        Paginated list of {items}.
    """
    service = {ModuleName}Service(db, tenant_context)
    return await service.list_{items}(page=page, page_size=page_size)
```

### 2. Service: apps/api/services/{module_name}.py
```python
"""
{Module Name} service layer.

Contains all business logic for {description}.
No HTTP concerns here — only business rules and orchestration.
"""
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession

from ..repositories.{module_name} import {ModuleName}Repository
from ..schemas.{module_name} import {ModelName}Response, {ModelName}ListResponse
from ..middleware.tenant import TenantContext


class {ModuleName}Service:
    """Service for {module_name} business logic."""

    def __init__(self, db: AsyncSession, tenant_context: TenantContext) -> None:
        self._repo = {ModuleName}Repository(db, tenant_context)

    async def list_{items}(self, page: int, page_size: int) -> {ModelName}ListResponse:
        """
        Retrieve paginated {items} for the current tenant.

        Args:
            page: Page number.
            page_size: Items per page.

        Returns:
            Paginated response with {items} and metadata.
        """
        items, total = await self._repo.list(page=page, page_size=page_size)
        return {ModelName}ListResponse(
            items=[{ModelName}Response.model_validate(item) for item in items],
            total=total,
            page=page,
            page_size=page_size,
        )
```

### 3. Repository: apps/api/repositories/{module_name}.py
```python
"""
{Module Name} repository layer.

All database access for {module_name} goes here.
No business logic — only database queries.
"""
from uuid import UUID
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.{module_name} import {ModelName}
from ..middleware.tenant import TenantContext


class {ModuleName}Repository:
    """Database access for {module_name}."""

    def __init__(self, db: AsyncSession, tenant_context: TenantContext) -> None:
        self._db = db
        self._tenant_context = tenant_context

    async def list(self, page: int, page_size: int) -> tuple[list[{ModelName}], int]:
        """
        Fetch paginated {items} for the current tenant.
        Tenant isolation enforced by tenant_context.schema.
        """
        offset = (page - 1) * page_size
        query = (
            select({ModelName})
            .where({ModelName}.is_deleted == False)
            .offset(offset)
            .limit(page_size)
        )
        count_query = (
            select(func.count())
            .select_from({ModelName})
            .where({ModelName}.is_deleted == False)
        )
        result = await self._db.execute(query)
        count_result = await self._db.execute(count_query)
        return result.scalars().all(), count_result.scalar_one()
```

### 4. Schema: apps/api/schemas/{module_name}.py
```python
"""Pydantic schemas for {module_name} API requests and responses."""
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, ConfigDict


class {ModelName}Base(BaseModel):
    """Base schema with shared fields."""
    model_config = ConfigDict(from_attributes=True)


class {ModelName}Response({ModelName}Base):
    """Response schema returned to API clients."""
    id: UUID
    tenant_id: UUID
    created_at: datetime


class {ModelName}ListResponse(BaseModel):
    """Paginated list response."""
    items: list[{ModelName}Response]
    total: int
    page: int
    page_size: int


class {ModelName}CreateRequest({ModelName}Base):
    """Request schema for creating a new {item}."""
    pass  # Add fields here
```

### 5. Test: apps/api/tests/test_{module_name}_unit.py
```python
"""Unit tests for {module_name} service."""
import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from ..services.{module_name} import {ModuleName}Service


@pytest.fixture
def mock_repo():
    return AsyncMock()


@pytest.fixture
def service(mock_repo):
    service = {ModuleName}Service.__new__({ModuleName}Service)
    service._repo = mock_repo
    return service


@pytest.mark.asyncio
async def test_list_{items}_returns_paginated_results(service, mock_repo):
    # Arrange
    mock_items = [MagicMock() for _ in range(3)]
    mock_repo.list.return_value = (mock_items, 3)

    # Act
    result = await service.list_{items}(page=1, page_size=20)

    # Assert
    assert result.total == 3
    assert result.page == 1
    mock_repo.list.assert_called_once_with(page=1, page_size=20)
```

---

## SKILL: new-ml-model
## Trigger: "add a new ML model for [X]" or "create [X] predictor"

When adding a new ML model, generate ALL of these files:

### 1. Model: apps/ml/models/{model_name}.py
```python
"""
{Model Name} — {description}.

Model type: {e.g. Random Forest / U-Net / ResNet-50}
Training data: {describe}
Accuracy: {X}% on validation set
Deployed since: {date}
"""
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import UUID

import joblib
import numpy as np
import shap


@dataclass
class {ModelName}Input:
    """Input features for {model_name} prediction."""
    # Define input fields here


@dataclass
class {ModelName}Prediction:
    """Structured output from {model_name} inference."""
    model_name: str
    model_version: str
    tenant_id: UUID
    prediction: float          # 0.0 to 1.0
    confidence: float          # 0.0 to 1.0
    shap_values: dict          # Feature importance — required for all models
    input_hash: str            # SHA256 of input features
    inference_time_ms: int
    timestamp: datetime
    requires_human_review: bool


class {ModelName}:
    """
    {Model Name} inference class.

    SHAP values are computed for every prediction.
    Predictions below confidence threshold require human review.
    """

    MODEL_NAME = "{model_name}"
    CONFIDENCE_THRESHOLD_HIGH = 0.90
    CONFIDENCE_THRESHOLD_MEDIUM = 0.75

    def __init__(self, model_path: Path, version: str) -> None:
        self._model = joblib.load(model_path)
        self._explainer = shap.TreeExplainer(self._model)
        self._version = version

    def predict(
        self,
        input_data: {ModelName}Input,
        tenant_id: UUID,
    ) -> {ModelName}Prediction:
        """
        Run inference and return structured prediction with SHAP values.

        Args:
            input_data: Input features.
            tenant_id: Tenant identifier (for audit logging).

        Returns:
            Structured prediction with confidence and explainability.
        """
        start_time = datetime.utcnow()

        features = self._extract_features(input_data)
        input_hash = self._hash_input(features)

        raw_prediction = self._model.predict_proba([features])[0][1]
        shap_values = self._explainer.shap_values(np.array([features]))

        inference_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)

        return {ModelName}Prediction(
            model_name=self.MODEL_NAME,
            model_version=self._version,
            tenant_id=tenant_id,
            prediction=float(raw_prediction),
            confidence=float(raw_prediction),
            shap_values=self._format_shap(shap_values, features),
            input_hash=input_hash,
            inference_time_ms=inference_ms,
            timestamp=datetime.utcnow(),
            requires_human_review=raw_prediction < self.CONFIDENCE_THRESHOLD_MEDIUM,
        )

    def _extract_features(self, input_data: {ModelName}Input) -> list[float]:
        """Extract feature vector from input data."""
        raise NotImplementedError  # Implement per model

    def _hash_input(self, features: list[float]) -> str:
        return hashlib.sha256(json.dumps(features).encode()).hexdigest()

    def _format_shap(self, shap_values: np.ndarray, features: list) -> dict:
        return {f"feature_{i}": float(v) for i, v in enumerate(shap_values[0])}
```

### 2. Test: apps/ml/tests/test_{model_name}_unit.py
```python
"""Unit tests for {model_name}."""
import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from uuid import uuid4
from pathlib import Path


@pytest.fixture
def mock_model_path(tmp_path):
    return tmp_path / "model.joblib"


def test_{model_name}_prediction_includes_shap_values():
    # Test that SHAP values are always present
    pass


def test_{model_name}_low_confidence_requires_human_review():
    # Test that predictions below threshold are flagged
    pass


def test_{model_name}_returns_structured_prediction():
    # Test all required fields are present
    pass
```

---

## SKILL: new-tenant
## Trigger: "add a new tenant" or "onboard [state/country]"

Steps to follow when adding a new tenant:

1. Add tenant block to tenants.yaml
2. Run: `python scripts/generate_tenant.py --tenant-id {id}`
3. Run: `python scripts/validate_tenant.py --tenant-id {id}`
4. Run: `python scripts/run_migrations.py --tenant-id {id}`
5. Verify schema created: `SELECT schema_name FROM information_schema.schemata WHERE schema_name = 'tenant_{id}';`
6. Add satellite ROI to ingestion scheduler
7. Run smoke test: `python scripts/test_tenant.py --tenant-id {id}`

Never add a tenant by modifying application code. Only tenants.yaml and the provisioning scripts.

---

## SKILL: new-database-migration
## Trigger: "add a column/table" or "change the schema"

When creating a database migration:

1. NEVER drop a column in a migration — mark as deprecated first
2. NEVER rename a column in one migration — add new + migrate data + remove old
3. ALWAYS add a comment explaining why the migration exists
4. Always test rollback before merging

```python
"""
Migration: {description}
Reason: {why this change is needed}
Ticket: {ticket number}
"""
from alembic import op
import sqlalchemy as sa

def upgrade() -> None:
    # Always add columns as nullable first, then backfill, then make NOT NULL
    op.add_column(
        "table_name",
        sa.Column("new_column", sa.String(255), nullable=True),
        schema="%(tenant_schema)s",  # Applied to all tenant schemas
    )

def downgrade() -> None:
    op.drop_column("table_name", "new_column", schema="%(tenant_schema)s")
```

---

## SKILL: new-alert-notification
## Trigger: "send an alert" or "notify agencies about [X]"

All alert notifications must follow this pattern:

1. Check confidence threshold (see CLAUDE.md Section 9)
2. Check `requires_human_review` flag — if true, queue for review, do not send
3. Generate multilingual message via Claude API (6 languages)
4. Write to alert_events table with full audit trail
5. Send via appropriate gateway (Termii for NG, Twilio for international)
6. Update alert status
7. Never retry a failed alert without exponential backoff

```python
async def send_conflict_alert(
    prediction: ConflictPrediction,
    tenant_id: UUID,
    affected_agencies: list[Agency],
) -> AlertResult:
    """
    Send a conflict alert to relevant agencies.

    Confidence check enforced. Human review required below threshold.
    All sends logged to audit table.
    """
    if prediction.requires_human_review:
        await queue_for_human_review(prediction, tenant_id)
        return AlertResult(sent=False, reason="queued_for_review")

    messages = await generate_multilingual_alert(prediction)

    for agency in affected_agencies:
        await send_sms(
            to=agency.sms_number,
            message=messages[agency.language],
            tenant_id=tenant_id,
        )
        await log_to_audit(
            action="ALERT_SENT",
            resource_type="conflict_alert",
            tenant_id=tenant_id,
        )

    return AlertResult(sent=True, recipients=len(affected_agencies))
```

---

## SKILL: generate-audit-package
## Trigger: "generate audit package" or "prepare for government review"

Run `make audit` which executes `scripts/audit_package.sh`.

The audit package must contain:
1. `security-scan.json` — Bandit output, zero HIGH/CRITICAL findings
2. `dependency-audit.json` — pip-audit output, zero known CVEs
3. `coverage-report.html` — Test coverage >= 85% on all modules
4. `compliance-mapping.md` — Maps each NDPA 2023 article to implementation
5. `data-flow-diagram.png` — Shows data movement and tenant isolation
6. `api-spec.json` — OpenAPI spec exported from FastAPI
7. `tenant-isolation-proof.sql` — SQL queries showing schema separation
8. `audit-log-sample.json` — Sample audit log entries (anonymised)

Never send an audit package that has any HIGH or CRITICAL security findings.
Never send an audit package with test coverage below 85%.
