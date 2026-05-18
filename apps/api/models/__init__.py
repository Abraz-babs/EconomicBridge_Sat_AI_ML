"""Re-export every ORM model so Alembic autogenerate can see them.

Adding a new model? Import it here AND add the import to this list, otherwise
`alembic revision --autogenerate` won't pick it up.

`AlertEvent` lives in per-tenant schemas — its table is NOT created in the
public schema and Alembic autogenerate is intentionally not relied on for it.
The DDL is hand-written in migrations/versions/0003_create_alert_events.py and
applied to every pilot tenant schema there.
"""
from models.alert_event import AlertEvent
from models.audit_log import AuditLog
from models.dpa import DataProcessingAgreement, DataSubjectRequest
from models.organisation import Organisation
from models.refresh_token import RefreshToken
from models.user import User

__all__ = [
    "Organisation",
    "User",
    "RefreshToken",
    "AuditLog",
    "AlertEvent",
    "DataProcessingAgreement",
    "DataSubjectRequest",
]
