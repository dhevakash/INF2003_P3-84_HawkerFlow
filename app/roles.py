"""Canonical application roles; legacy roles require the explicit DB migration."""
from enum import StrEnum


class Role(StrEnum):
    ADMIN = 'admin'
    STAFF = 'staff'
    CUSTOMER = 'customer'


VALID_ROLES = frozenset(role.value for role in Role)
ROLE_CHECK_SQL = 'role IN (' + ','.join(repr(role.value) for role in Role) + ')'
