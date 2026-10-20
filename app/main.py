"""HTTP entry point and static UI for HawkerFlow."""
import logging
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
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

app = FastAPI(title='HawkerFlow', version='0.1.0', lifespan=lifespan,
              docs_url=None, redoc_url=None)
app.add_middleware(GZipMiddleware, minimum_size=1000, compresslevel=5)

@app.middleware('http')
async def security_headers(request: Request, call_next):
    is_documentation = request.url.path in {'/docs', '/redoc'}
    if is_documentation:
        request.state.csp_nonce = secrets.token_urlsafe(24)
    response = await call_next(request)
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['X-Frame-Options']='DENY'
    response.headers['Referrer-Policy']='same-origin'
    response.headers['Permissions-Policy']='camera=(), microphone=(), geolocation=()'
    script_sources = "'self'"
    style_sources = "'self' 'unsafe-inline'"
    image_sources = "'self' data:"
    worker_policy = ''
    if is_documentation:
        # The existing docs libraries come from jsDelivr. A unique nonce permits
        # only our generated script tags; application pages stay self-only.
        script_sources += f" 'nonce-{request.state.csp_nonce}'"
        if request.url.path == '/docs':
            style_sources += ' https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css'
        else:
            # ReDoc indexes API search in a local blob worker and supplies a
            # small attribution logo. These allowances belong to /redoc only.
            image_sources += ' https://cdn.redoc.ly/redoc/logo-mini.svg'
            worker_policy = "; worker-src 'self' blob:"
        response.headers['Referrer-Policy']='no-referrer'
    response.headers['Content-Security-Policy']=(
        f"default-src 'self'; script-src {script_sources}; style-src {style_sources}; "
        f"img-src {image_sources}; connect-src 'self'; frame-ancestors 'none'; "
        "base-uri 'self'; object-src 'none'; form-action 'self'"
        + worker_policy
    )
    if request.url.path.startswith('/api/') or is_documentation:
        response.headers['Cache-Control']='no-store'
    elif request.url.path in {'/', '/about'} or request.url.path.startswith('/static/'):
        # Keep conditional caching efficient while revalidating rebuilt assets.
        response.headers['Cache-Control']='no-cache'
    return response

@app.exception_handler(SQLAlchemyError)
async def unavailable_sql(request, exception):
    # SQLAlchemy exception text/tracebacks may contain bound customer data or
    # credentials. Keep operational metadata without statements or parameters.
    log.error('SQL operation failed (%s)', type(exception).__name__)
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

@app.get('/about', include_in_schema=False)
def about():
    return FileResponse(STATIC/'info.html')

def nonce_documentation(response: HTMLResponse, request: Request):
    html = response.body.decode('utf-8')
    html = html.replace('<script', f'<script nonce="{request.state.csp_nonce}"')
    return HTMLResponse(html)

@app.get('/docs', include_in_schema=False)
def documentation(request: Request):
    return nonce_documentation(get_swagger_ui_html(
        openapi_url=app.openapi_url, title='HawkerFlow API documentation',
        swagger_favicon_url='data:,',
        swagger_ui_parameters={'validatorUrl': None},
    ), request)

@app.get('/redoc', include_in_schema=False)
def reference(request: Request):
    return nonce_documentation(get_redoc_html(
        openapi_url=app.openapi_url, title='HawkerFlow API reference',
        redoc_favicon_url='data:,', with_google_fonts=False,
    ), request)
