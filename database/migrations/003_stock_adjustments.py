"""Add audited stock corrections without rewriting existing inventory or orders.

Stop application writes and verify a SQL backup before applying to a live database.
MariaDB DDL commits implicitly; the table creation and ALTER are restartable.
"""
import argparse
import hashlib
import json
import os
import re

from sqlalchemy import create_engine, inspect, text
from app.models import StockAdjustment, STOCK_MOVEMENT_ORIGIN_SQL

OLD_ORIGIN = ('(order_id IS NOT NULL AND receipt_id IS NULL AND delta < 0) OR '
              '(order_id IS NULL AND receipt_id IS NOT NULL AND delta > 0)')


def normalize(clause):
    return re.sub(r'[\s`()]+', '', clause.lower())


def snapshot(connection):
    """Fingerprint original columns, excluding only this migration's additions."""
    inspector = inspect(connection)
    quote = connection.dialect.identifier_preparer.quote
    result = {}
    for table in sorted(inspector.get_table_names()):
        if table == 'stock_adjustments':
            continue
        columns = [column['name'] for column in inspector.get_columns(table)
                   if not (table == 'stock_movements' and column['name'] == 'adjustment_id')]
        rows = connection.exec_driver_sql('SELECT ' + ','.join(map(quote, columns)) + ' FROM ' + quote(table))
        encoded = sorted(json.dumps(dict(row), default=str, sort_keys=True) for row in rows.mappings())
        result[table] = hashlib.sha256('\n'.join(encoded).encode()).hexdigest()
    return result


def upgrade(engine, database, *, allow_live=False):
    if engine.dialect.name not in {'mysql', 'mariadb'} or engine.url.database != database:
        raise ValueError('An explicit matching MariaDB database is required.')
    if not allow_live and not re.fullmatch(r'hawkerflow_[a-zA-Z0-9_]+_test', database):
        raise ValueError('Use a dedicated hawkerflow_*_test database or explicit --allow-live.')
    lock = 'hf_stock_' + hashlib.sha256(database.encode()).hexdigest()[:32]
    with engine.connect() as connection:
        if connection.execute(text('SELECT GET_LOCK(:name, 10)'), {'name': lock}).scalar_one() != 1:
            raise RuntimeError('Another stock migration holds the lock.')
        connection.commit()
        try:
            before = snapshot(connection)
            inspector = inspect(connection)
            columns = {column['name']: column for column in inspector.get_columns('stock_movements')}
            checks = {check['name']: check['sqltext'] for check in inspector.get_check_constraints('stock_movements')}
            existing = 'adjustment_id' in columns
            expected = STOCK_MOVEMENT_ORIGIN_SQL if existing else OLD_ORIGIN
            if normalize(checks.get('ck_movement_origin', '')) != normalize(expected):
                raise RuntimeError('Unfamiliar stock movement origin constraint. No schema was changed.')
            if existing:
                foreign_keys = inspector.get_foreign_keys('stock_movements')
                if (not columns['adjustment_id']['nullable'] or
                    not any(fk['constrained_columns'] == ['adjustment_id'] and
                            fk['referred_table'] == 'stock_adjustments' and fk['referred_columns'] == ['id']
                            for fk in foreign_keys)):
                    raise RuntimeError('Unfamiliar stock adjustment column or foreign key.')
            connection.commit()
            StockAdjustment.__table__.create(connection, checkfirst=True)
            connection.commit()
            if not existing:
                connection.exec_driver_sql('ALTER TABLE stock_movements '
                    'ADD COLUMN adjustment_id INTEGER NULL, '
                    'ADD CONSTRAINT fk_stock_movement_adjustment FOREIGN KEY (adjustment_id) REFERENCES stock_adjustments(id), '
                    'DROP CONSTRAINT ck_movement_origin, '
                    'ADD CONSTRAINT ck_movement_origin CHECK (' + STOCK_MOVEMENT_ORIGIN_SQL + ')')
                connection.commit()
            if snapshot(connection) != before:
                raise RuntimeError('Historical data changed. Keep the app stopped and inspect the backup.')
            return {'database': database, 'status': 'already_applied' if existing else 'applied',
                    'all_existing_rows_preserved': True}
        finally:
            connection.rollback()
            released = connection.execute(text('SELECT RELEASE_LOCK(:name)'), {'name': lock}).scalar_one()
            connection.commit()
            if released != 1:
                raise RuntimeError('The stock migration lock was not released.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', required=True)
    parser.add_argument('--allow-live', action='store_true')
    args = parser.parse_args()
    url = os.getenv('STOCK_MIGRATION_DATABASE_URL')
    if not url:
        parser.error('Set STOCK_MIGRATION_DATABASE_URL explicitly.')
    engine = create_engine(url, pool_pre_ping=True)
    try:
        print(json.dumps(upgrade(engine, args.database, allow_live=args.allow_live), indent=2))
    finally:
        engine.dispose()


if __name__ == '__main__':
    main()
