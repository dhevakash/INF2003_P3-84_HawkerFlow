"""Disposable UI preview only; refuses every non-fixture database."""
import os
import re

from app.analytics import initialize_views
from app.cli import seed_mongo, seed_sql
from app.database import Base, engine
from app.nosql import initialize_mongo
from app.schemas import InitialAdminInput
from app.services.accounts import bootstrap_admin


def main():
    name = os.environ.get('UI_FIXTURE_DATABASE', '')
    if (os.environ.get('RUN_UI_INTEGRATION') != '1'
            or not re.fullmatch(r'hawkerflow_ui_[0-9a-f]{32}_test', name)
            or engine.url.database != name or os.environ.get('MONGO_DATABASE') != name):
        raise RuntimeError('This preview requires a uniquely owned, disposable Step 7 SQL/Mongo test database.')
    Base.metadata.create_all(engine)
    initialize_views(engine)
    initialize_mongo()
    bootstrap_admin(engine, lambda: InitialAdminInput(email='ui-admin@example.test',
                                                    password='UiAdminTestPass123!'))
    seed_sql()
    seed_mongo()
    from app.main import app

    @app.get('/__test_fixture__', include_in_schema=False)
    def marker():
        return {'purpose': 'disposable-step7-ui-test', 'database': name}

    import uvicorn
    uvicorn.run(app, host='0.0.0.0', port=8000)


if __name__ == '__main__':
    main()
