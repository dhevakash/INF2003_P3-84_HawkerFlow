import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / '.env')
DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///./preview.sqlite')
MONGO_URI = os.getenv('MONGO_URI', '')
MONGO_DATABASE = os.getenv('MONGO_DATABASE', 'hawkerflow')
JWT_SECRET = os.getenv('JWT_SECRET', 'local-demo-only-change-before-sharing-123456789')
APP_ENV = os.getenv('APP_ENV', 'development')
if APP_ENV != 'development' and (JWT_SECRET.startswith('local-demo') or len(JWT_SECRET) < 32):
    raise RuntimeError('Set a random JWT_SECRET of at least 32 characters outside development.')
