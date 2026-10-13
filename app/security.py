"""Password hashing and signed, expiring bearer sessions for the local prototype."""
import base64
import hashlib
import hmac
import json
import secrets
import time
from collections import defaultdict, deque
from threading import Lock
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session
from .config import settings
from .db import get_session

bearer = HTTPBearer(auto_error=False)
_attempts = defaultdict(deque)
_attempt_lock = Lock()

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 310000)
    return 'pbkdf2_sha256$310000$' + salt.hex() + '$' + digest.hex()

def verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, rounds, salt, stored = encoded.split('$')
        if scheme != 'pbkdf2_sha256':
            return False
        actual = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), int(rounds))
        return hmac.compare_digest(actual.hex(), stored)
    except (ValueError, TypeError):
        return False

def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b'=').decode()

def issue_token(user_id: int) -> str:
    body = _b64(json.dumps({'sub':user_id,'exp':int(time.time()) + settings.token_minutes*60}, separators=(',',':')).encode())
    return body + '.' + _b64(hmac.digest(settings.secret_key.encode(), body.encode(), 'sha256'))

def token_subject(token: str) -> int:
    try:
        body, signature = token.split('.')
        expected = _b64(hmac.digest(settings.secret_key.encode(), body.encode(), 'sha256'))
        if not hmac.compare_digest(signature, expected):
            raise ValueError('signature')
        payload = json.loads(base64.urlsafe_b64decode(body+'='*((4-len(body)%4)%4)))
        if type(payload['sub']) is not int or payload['exp'] <= time.time():
            raise ValueError('expired')
        return payload['sub']
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        raise HTTPException(401, 'Invalid or expired sign-in. Please sign in again.')

def user_dict(user):
    return {key:getattr(user,key) for key in ('id','name','email','role','customer_id','branch_id')}

def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer), session: Session = Depends(get_session)):
    from .models import User
    if credentials is None:
        raise HTTPException(401,'Sign in to continue.')
    user = session.get(User, token_subject(credentials.credentials))
    if user is None or not user.is_active:
        raise HTTPException(401,'Account is unavailable.')
    return user

def require_roles(*roles):
    def dependency(user=Depends(current_user)):
        if user.role not in roles:
            raise HTTPException(403,'Your role does not allow this action.')
        return user
    return dependency

def throttle_login(request: Request):
    key = request.client.host if request.client else 'local'
    now = time.monotonic()
    with _attempt_lock:
        recent = _attempts[key]
        while recent and recent[0] < now-60:
            recent.popleft()
        if len(recent) >= 30:
            raise HTTPException(429,'Too many sign-in attempts. Try again in one minute.')
        recent.append(now)
