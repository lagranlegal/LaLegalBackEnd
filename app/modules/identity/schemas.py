from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr


class UserOut(BaseModel):
    id: UUID
    full_name: str
    email: str
    role_id: UUID
    status: str
    created_at: datetime


class InviteUserIn(BaseModel):
    email: EmailStr
    full_name: str
    role_id: UUID


class UpdateUserRoleIn(BaseModel):
    role_id: UUID


class RoleOut(BaseModel):
    id: UUID
    name: str
    description: str | None
    is_seed: bool
    active: bool


class RoleCreateIn(BaseModel):
    name: str
    description: str | None = None
    clone_from_role_id: UUID | None = None


class RoleRenameIn(BaseModel):
    name: str
    description: str | None = None


class RolePermissionsIn(BaseModel):
    permission_codes: list[str]


class PermissionOut(BaseModel):
    id: UUID
    code: str
    module: str
    action: str
    is_special: bool
    description: str | None
