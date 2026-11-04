"""Add an optional customer birthday without changing existing account/history data.

Rehearse on a restored backup before using the explicit --allow-live option.
"""
import argparse
import hashlib
import json
import os
import re

from sqlalchemy import Date, create_engine, inspect, text


def snapshot(connection, *, include_birthday=False):
    quote = connection.dialect.identifier_preparer.quote
    result = {}
    for table in sorted(inspect(connection).get_table_names()):
        columns = [column['name'] for column in inspect(connection).get_columns(table)
                   if include_birthday or table != 'customers' or column['name'] != 'birthday']
        rows = sorted(json.dumps(dict(row), default=str, sort_keys=True) for row in connection.exec_driver_sql(
            'SELECT '+','.join(quote(column) for column in columns)+' FROM '+quote(table)).mappings())
        result[table] = {'rows': len(rows), 'sha256': hashlib.sha256('\n'.join(rows).encode()).hexdigest()}
    return result


def upgrade(engine, database, *, allow_live=False):
    if engine.dialect.name not in {'mysql', 'mariadb'} or engine.url.database != database:
        raise ValueError('An explicit matching MariaDB database is required.')
    if not allow_live and not re.fullmatch(r'hawkerflow_[a-zA-Z0-9_]+_test', database):
        raise ValueError('Use a dedicated hawkerflow_*_test database or explicit --allow-live.')
    lock = 'hf_birthday_'+hashlib.sha256(database.encode()).hexdigest()[:32]
    with engine.connect() as connection:
        if connection.execute(text('SELECT GET_LOCK(:name, 10)'), {'name': lock}).scalar_one() != 1:
            raise RuntimeError('Another birthday migration holds the lock.')
        connection.commit()
        try:
            columns = {column['name']: column for column in inspect(connection).get_columns('customers')}
            existing = 'birthday' in columns
            if existing and (not isinstance(columns['birthday']['type'], Date)
                             or not columns['birthday']['nullable'] or columns['birthday']['default'] is not None):
                raise RuntimeError('Unfamiliar birthday column definition; no change was applied.')
            before = snapshot(connection, include_birthday=existing)
            connection.commit()
            if not existing:
                connection.exec_driver_sql('ALTER TABLE customers ADD COLUMN birthday DATE NULL')
                connection.commit()
                if connection.exec_driver_sql('SELECT COUNT(*) FROM customers WHERE birthday IS NOT NULL').scalar_one():
                    raise RuntimeError('Existing birthdays must remain unset after adding the column.')
            after = snapshot(connection, include_birthday=existing)
            if before != after:
                raise RuntimeError('Existing data changed during migration. Inspect concurrent writes and the verified backup.')
            return {'database': database, 'status': 'already_applied' if existing else 'applied',
                    'all_existing_rows_preserved': True, 'sql_tables_checked': len(before),
                    'accounts': before['users']['rows'], 'orders': before['orders']['rows']}
        finally:
            connection.rollback()
            released = connection.execute(text('SELECT RELEASE_LOCK(:name)'), {'name': lock}).scalar_one()
            connection.commit()
            if released != 1:
                raise RuntimeError('The birthday migration lock was not released.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', required=True)
    parser.add_argument('--allow-live', action='store_true')
    args = parser.parse_args()
    url = os.getenv('BIRTHDAY_MIGRATION_DATABASE_URL')
    if not url:
        parser.error('Set BIRTHDAY_MIGRATION_DATABASE_URL explicitly.')
    engine = create_engine(url, pool_pre_ping=True)
    try:
        print(json.dumps(upgrade(engine, args.database, allow_live=args.allow_live), indent=2))
    finally:
        engine.dispose()
