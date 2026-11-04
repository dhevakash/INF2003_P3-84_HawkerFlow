"""Add the points correction audit table without modifying existing records.

Use a verified SQL backup and test restore before an explicit live upgrade.
"""
import argparse
import hashlib
import json
import os
import re

from sqlalchemy import CheckConstraint, String, create_engine, inspect, text
from app.models import LoyaltyAdjustment


def normalized(clause):
    return re.sub(r'[\s`()]+', '', str(clause).lower().replace('octet_length', 'length'))


def snapshot(connection):
    quote = connection.dialect.identifier_preparer.quote
    result = {}
    for table in sorted(inspect(connection).get_table_names()):
        if table == 'loyalty_adjustments':
            continue
        rows = sorted(json.dumps(dict(row), default=str, sort_keys=True)
                      for row in connection.exec_driver_sql('SELECT * FROM '+quote(table)).mappings())
        result[table] = hashlib.sha256('\n'.join(rows).encode()).hexdigest()
    return result


def upgrade(engine, database, *, allow_live=False):
    if engine.dialect.name not in {'mysql', 'mariadb'} or engine.url.database != database:
        raise ValueError('An explicit matching MariaDB database is required.')
    if not allow_live and not re.fullmatch(r'hawkerflow_[a-zA-Z0-9_]+_test', database):
        raise ValueError('Use a dedicated hawkerflow_*_test database or explicit --allow-live.')
    lock = 'hf_points_'+hashlib.sha256(database.encode()).hexdigest()[:32]
    with engine.connect() as connection:
        if connection.execute(text('SELECT GET_LOCK(:name, 10)'), {'name': lock}).scalar_one() != 1:
            raise RuntimeError('Another points migration holds the lock.')
        connection.commit()
        try:
            before = snapshot(connection)
            existing = inspect(connection).has_table('loyalty_adjustments')
            if existing:
                columns = {column['name']: column for column in inspect(connection).get_columns('loyalty_adjustments')}
                if set(columns) != set(LoyaltyAdjustment.__table__.columns.keys()) or any(column['nullable'] for column in columns.values()):
                    raise RuntimeError('Unfamiliar loyalty adjustment table definition.')
                for name, column in columns.items():
                    expected_type = LoyaltyAdjustment.__table__.c[name].type
                    if not isinstance(column['type'], type(expected_type)) or (isinstance(expected_type, String) and column['type'].length != expected_type.length):
                        raise RuntimeError('Unfamiliar loyalty adjustment column type: '+name)
                expected_checks = {constraint.name: normalized(constraint.sqltext)
                    for constraint in LoyaltyAdjustment.__table__.constraints if isinstance(constraint, CheckConstraint)}
                actual_checks = {check['name']: normalized(check['sqltext'])
                    for check in inspect(connection).get_check_constraints('loyalty_adjustments')}
                if actual_checks != expected_checks:
                    raise RuntimeError('Unfamiliar loyalty adjustment constraints.')
                foreign_keys = {(tuple(fk['constrained_columns']), fk['referred_table'], tuple(fk['referred_columns']))
                    for fk in inspect(connection).get_foreign_keys('loyalty_adjustments')}
                if foreign_keys != {(('customer_id',), 'customers', ('id',)), (('actor_user_id',), 'users', ('id',))}:
                    raise RuntimeError('Unfamiliar loyalty adjustment foreign keys.')
            connection.commit()
            LoyaltyAdjustment.__table__.create(connection, checkfirst=True)
            connection.commit()
            if snapshot(connection) != before:
                raise RuntimeError('Existing data changed during migration. Inspect the verified backup.')
            return {'database': database, 'status': 'already_applied' if existing else 'applied',
                    'all_existing_rows_preserved': True}
        finally:
            connection.rollback()
            released = connection.execute(text('SELECT RELEASE_LOCK(:name)'), {'name': lock}).scalar_one()
            connection.commit()
            if released != 1:
                raise RuntimeError('The points migration lock was not released.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', required=True)
    parser.add_argument('--allow-live', action='store_true')
    args = parser.parse_args()
    url = os.getenv('POINTS_MIGRATION_DATABASE_URL')
    if not url:
        parser.error('Set POINTS_MIGRATION_DATABASE_URL explicitly.')
    engine = create_engine(url, pool_pre_ping=True)
    try:
        print(json.dumps(upgrade(engine, args.database, allow_live=args.allow_live), indent=2))
    finally:
        engine.dispose()
