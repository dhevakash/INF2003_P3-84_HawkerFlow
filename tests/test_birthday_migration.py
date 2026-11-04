"""Migration target checks must fail before any database connection is opened."""
import importlib.util
from pathlib import Path
import pytest
from sqlalchemy import create_engine


@pytest.mark.parametrize('url,database', [('sqlite://', 'hawkerflow_preview_test'),
    ('mysql+pymysql://unused:unused@localhost/hawkerflow', 'hawkerflow'),
    ('mysql+pymysql://unused:unused@localhost/hawkerflow_other_test', 'hawkerflow_preview_test')])
def test_birthday_migration_requires_an_explicit_safe_matching_database(url, database):
    path = Path(__file__).resolve().parents[1]/'database/migrations/005_customer_birthday.py'
    spec = importlib.util.spec_from_file_location('birthday_migration', path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine(url)
    try:
        with pytest.raises(ValueError):
            migration.upgrade(engine, database)
    finally:
        engine.dispose()
