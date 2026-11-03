"""Coordinated role/activation upgrade with an explicit database target.

MariaDB DDL commits implicitly. Phases are restartable and no accounts are
deleted. The standalone 001 CLI remains test-only; this release entry point
requires --allow-live plus the exact database name for a live installation.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path

from sqlalchemy import create_engine, text


def load_roles():
    spec = importlib.util.spec_from_file_location('roles_001', Path(__file__).with_name('001_admin_staff_customer.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fingerprint(rows):
    encoded = sorted(json.dumps(row, default=str, sort_keys=True, separators=(',', ':')) for row in rows)
    return hashlib.sha256('\n'.join(encoded).encode()).hexdigest()


def snapshot(connection):
    names = list(connection.execute(text('SELECT TABLE_NAME FROM information_schema.TABLES '
        'WHERE TABLE_SCHEMA=DATABASE() ORDER BY TABLE_NAME')).scalars())
    return {name: fingerprint([dict(row) for row in connection.exec_driver_sql('SELECT * FROM ' +
        connection.dialect.identifier_preparer.quote(name)).mappings()]) for name in names if name != 'users'}


def upgrade(engine, database, *, allow_live=False):
    roles = load_roles()
    if engine.url.database != database:
        raise ValueError('The explicit database name does not match the connection.')
    roles.validate_target(engine, database if allow_live else None)
    lock = 'hf_upgrade_' + hashlib.sha256(database.encode()).hexdigest()[:32]
    with engine.connect() as connection:
        if connection.execute(text('SELECT GET_LOCK(:name, 10)'), {'name': lock}).scalar_one() != 1:
            raise RuntimeError('Another coordinated upgrade holds the lock.')
        connection.commit()
        try:
            before = [dict(row) for row in connection.exec_driver_sql('SELECT * FROM users ORDER BY id').mappings()]
            history = snapshot(connection)
            columns = {row['COLUMN_NAME']: dict(row) for row in connection.execute(text(
                'SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE, COLUMN_DEFAULT FROM information_schema.COLUMNS '
                "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='users'")).mappings()}
            constraints = {row[0]: row[1] for row in connection.execute(text(
                "SELECT CONSTRAINT_NAME,CHECK_CLAUSE FROM information_schema.CHECK_CONSTRAINTS "
                "WHERE CONSTRAINT_SCHEMA=DATABASE() AND TABLE_NAME='users'"))}
            additions = []
            for name, definition, kind, default in [
                ('active', 'TINYINT(1) NOT NULL DEFAULT 1', 'tinyint', '1'),
                ('session_version', 'INT NOT NULL DEFAULT 0', 'int', '0')]:
                if name not in columns:
                    additions.append('ADD COLUMN ' + name + ' ' + definition)
                elif (columns[name]['DATA_TYPE'] != kind or columns[name]['IS_NULLABLE'] != 'NO'
                      or str(columns[name]['COLUMN_DEFAULT']).strip("'") != default):
                    raise RuntimeError('Unfamiliar account column definition: ' + name)
            for name, clause in [('ck_user_active', 'active IN (0,1)'),
                                 ('ck_user_session_version', 'session_version >= 0')]:
                if name not in constraints:
                    additions.append('ADD CONSTRAINT ' + name + ' CHECK (' + clause + ')')
                elif ''.join(constraints[name].replace('`', '').lower().split()) != ''.join(clause.lower().split()):
                    raise RuntimeError('Unfamiliar account constraint: ' + name)
            connection.commit()
            role_result = roles.migrate_roles(engine, expected_database=database if allow_live else None)
            if additions:
                connection.exec_driver_sql('ALTER TABLE users ' + ', '.join(additions))
                connection.commit()
            after = [dict(row) for row in connection.exec_driver_sql('SELECT * FROM users ORDER BY id').mappings()]
            expected = [{**row, 'role': roles.LEGACY_MAPPING.get(row['role'], row['role']),
                         'active': row.get('active', 1), 'session_version': row.get('session_version', 0)}
                        for row in before]
            if after != expected or snapshot(connection) != history:
                raise RuntimeError('Account/history preservation failed. Keep the application stopped and inspect the verified backup.')
            return {'database': database, 'status': 'applied' if additions or role_result['status'] == 'applied' else 'already_applied',
                    'accounts_preserved': len(after), 'role_changes': role_result['changed_user_ids'],
                    'all_other_account_fields_preserved': True, 'historical_tables_and_views_preserved': True,
                    'new_columns': [name for name in ('active','session_version') if name not in columns]}
        finally:
            connection.rollback()
            try:
                if connection.execute(text('SELECT RELEASE_LOCK(:name)'), {'name': lock}).scalar_one() != 1:
                    raise RuntimeError('The coordinated migration lock was not released.')
                connection.commit()
            except Exception:
                connection.invalidate()
                raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', required=True, help='Exact intended database; must match the explicit connection URL.')
    parser.add_argument('--allow-live', action='store_true', help='Coordinated live rollout only, after backup verification and stopping the app.')
    args = parser.parse_args()
    url = os.environ.get('ACCOUNT_MIGRATION_DATABASE_URL')
    if not url:
        parser.error('Set ACCOUNT_MIGRATION_DATABASE_URL explicitly; the live application URL is not selected implicitly.')
    engine = create_engine(url, pool_pre_ping=True)
    try:
        print(json.dumps(upgrade(engine, args.database, allow_live=args.allow_live), indent=2))
    finally:
        engine.dispose()


if __name__ == '__main__':
    main()
