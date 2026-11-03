from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import secrets
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from app.config import JWT_SECRET
from app.database import SessionLocal
from app.models import User
from app.roles import Role, VALID_ROLES


def hash_password(password):
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 600_000).hex()
    return f'pbkdf2_sha256$600000${salt}${digest}'


def verify_password(password, stored):
    try:
        scheme, rounds, salt, expected = stored.split('$')
        if scheme != 'pbkdf2_sha256':
            return False
        actual = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), int(rounds)).hex()
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def issue_token(user):
    return jwt.encode({'sub': str(user.id), 'ver': getattr(user, 'session_version', 0),
                      'exp': datetime.now(timezone.utc) + timedelta(hours=2)},
                      JWT_SECRET, algorithm='HS256')


@dataclass(frozen=True)
class Principal:
    id: int
    role: str
    customer_id: int | None


bearer = HTTPBearer(auto_error=False)


def principal_for(user):
    if not user.active:
        raise HTTPException(401, 'Please sign in again.')
    if user.role not in VALID_ROLES:
        raise HTTPException(403, 'This account has an unsupported role. Complete the account migration first.')
    if user.role == Role.CUSTOMER and user.customer_id is None:
        raise HTTPException(403, 'This customer account is not linked to a customer record.')
    return Principal(user.id, user.role, user.customer_id)


def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
    try:
        if credentials is None:
            raise ValueError('Missing bearer token')
        claims = jwt.decode(credentials.credentials, JWT_SECRET, algorithms=['HS256'], options={'require': ['exp', 'sub', 'ver']})
        with SessionLocal() as session:
            user = session.scalar(select(User).where(User.id == int(claims['sub'])))
            if not user:
                raise ValueError('Unknown user')
            if type(claims['ver']) is not int or claims['ver'] != user.session_version:
                raise ValueError('Revoked session')
            return principal_for(user)
    except (jwt.InvalidTokenError, ValueError, KeyError):
        raise HTTPException(401, 'Please sign in again.') from None


def require_roles(*roles):
    if not roles or not set(roles) <= VALID_ROLES:
        raise ValueError('Permission checks must explicitly allow known application roles.')
    def check(user: Principal = Depends(current_user)):
        if user.role not in roles:
            raise HTTPException(403, 'This action is not allowed for your role.')
        return user
    return check
