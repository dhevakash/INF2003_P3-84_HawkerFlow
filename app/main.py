from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pymongo.errors import DuplicateKeyError, OperationFailure, PyMongoError
from sqlalchemy.exc import IntegrityError
from app.config import ROOT
from app.routes import router
from app.services.checkout import BusinessError

app = FastAPI(title='HawkerFlow', version='0.1.0', description='INF2003 Team 84 working starter. See docs/STATUS.md.')
app.include_router(router)
app.mount('/static', StaticFiles(directory=ROOT / 'app/static'), name='static')


@app.get('/', include_in_schema=False)
def index():
    return FileResponse(ROOT / 'app/static/index.html')


@app.exception_handler(BusinessError)
def business_error(request: Request, exc: BusinessError):
    return JSONResponse(status_code=exc.status, content={'detail': str(exc)})


@app.exception_handler(IntegrityError)
def integrity_error(request: Request, exc: IntegrityError):
    return JSONResponse(status_code=409, content={'detail': 'A unique, foreign-key or check constraint rejected this change.'})


@app.exception_handler(PyMongoError)
def mongo_error(request: Request, exc: PyMongoError):
    if isinstance(exc, DuplicateKeyError):
        status, message = 409, 'A review already exists for this order.'
    elif isinstance(exc, OperationFailure) and exc.code == 121:
        status, message = 422, 'MongoDB rejected the document against its validator.'
    else:
        status, message = 503, 'MongoDB is unavailable. A completed SQL sale remains committed.'
    return JSONResponse(status_code=status, content={'detail': message})
