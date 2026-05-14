"""Re-export every ORM model so Alembic autogenerate can see them.

Adding a new model? Import it here AND add the import to this list, otherwise
`alembic revision --autogenerate` won't pick it up.
"""
from models.audit_log import AuditLog
from models.organisation import Organisation
from models.refresh_token import RefreshToken
from models.user import User

__all__ = ["Organisation", "User", "RefreshToken", "AuditLog"]
