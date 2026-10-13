"""HTTP entry point and static UI for HawkerFlow."""
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from pymongo.errors import PyMongoError
from .db import engine, get_session
from .security import current_user, issue_token, throttle_login, user_dict, verify_password

log = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app):
    from .mongo import initialize_mongo
    try:
        initialize_mongo()
    except PyMongoError:
        log.warning('MongoDB unavailable at startup; SQL workflows remain independent.')
    yield

app = FastAPI(title='HawkerFlow', version='0.1.0', lifespan=lifespan)

@app.middleware('http')
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['X-Frame-Options']='DENY'
    response.headers['Referrer-Policy']='same-origin'
    response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'"
    if request.url.path.startswith('/api/'):
        response.headers['Cache-Control']='no-store'
    return response

@app.exception_handler(SQLAlchemyError)
async def unavailable_sql(request, exception):
    log.exception('SQL operation failed')
    return JSONResponse(status_code=503,content={'detail':'The SQL store is unavailable or rejected this operation.'})

class LoginBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    email: str = Field(min_length=3,max_length=254)
    password: str = Field(min_length=1,max_length=256)

@app.post('/api/auth/login')
def login(body: LoginBody, request: Request, session: Session=Depends(get_session)):
    from .models import User
    throttle_login(request)
    user = session.scalar(select(User).where(User.email==body.email.strip().lower()))
    if user is None or not verify_password(body.password,user.password_hash) or not user.is_active:
        raise HTTPException(401,'Email or password is incorrect.')
    return {'access_token':issue_token(user.id),'token_type':'bearer','user':user_dict(user)}

@app.get('/api/auth/me')
def me(user=Depends(current_user)):
    return user_dict(user)

@app.get('/api/health')
def health():
    from .mongo import get_database
    checks={}
    try:
        with engine.connect() as connection:
            connection.execute(text('SELECT 1'))
        checks['sql']='connected'
    except SQLAlchemyError:
        checks['sql']='unavailable'
    try:
        get_database().command('ping')
        checks['mongo']='connected'
    except PyMongoError:
        checks['mongo']='unavailable'
    return {'status':'ready' if all(x=='connected' for x in checks.values()) else 'degraded','databases':checks}

from .sql_routes import router as sql_router
from .mongo_routes import router as mongo_router
from .advanced_routes import router as advanced_router
app.include_router(sql_router)
app.include_router(mongo_router)
app.include_router(advanced_router)
STATIC=Path(__file__).parent/'static'
app.mount('/static',StaticFiles(directory=STATIC),name='static')

@app.get('/',include_in_schema=False)
def index():
    return FileResponse(STATIC/'index.html')
