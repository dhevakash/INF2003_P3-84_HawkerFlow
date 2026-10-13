"""Sessions for MariaDB; SQLite is only used by explicitly configured unit tests."""
from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from .config import settings

class Base(DeclarativeBase):
    pass

kwargs = {'pool_pre_ping': True}
if settings.sql_url.startswith('sqlite'):
    kwargs['connect_args'] = {'check_same_thread': False}
else:
    kwargs['connect_args'] = {'connect_timeout': 5}
engine = create_engine(settings.sql_url, **kwargs)
if engine.dialect.name == 'sqlite':
    @event.listens_for(engine, 'connect')
    def enforce_sqlite_foreign_keys(connection, _):
        connection.execute('PRAGMA foreign_keys=ON')
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

def get_session():
    with SessionLocal() as session:
        yield session

def init_db():
    from . import models  # register every mapped table
    Base.metadata.create_all(engine)
    from .sql_views import create_views
    create_views(engine)
