"""Version 001: rehearse the Admin/Staff/Customer migration on MariaDB test copies.

MariaDB ALTER TABLE commits implicitly. Each phase is restartable; this migration
does not claim that one transaction can roll back all schema and data changes.
Live rollout is deliberately unavailable until the application upgrade is ready.
"""
import argparse
from collections import Counter
import hashlib
import json
import os
import re

from sqlalchemy import create_engine, text

MIGRATION_ID = '001_admin_staff_customer'
TARGET_ROLES = ('admin', 'staff', 'customer')
LEGACY_MAPPING = {'manager': 'staff', 'cashier': 'staff'}
TRANSITION_ROLES = ('manager', 'cashier', 'admin', 'staff', 'customer')


def validate_target(engine, expected_database=None):
    name = engine.url.database or ''
    if engine.dialect.name not in {'mysql', 'mariadb'}:
        raise ValueError('This migration requires MariaDB.')
    if expected_database is not None:
        if name != expected_database or not re.fullmatch(r'[A-Za-z0-9_]+', name):
            raise ValueError('The explicitly confirmed database does not match the connection.')
    elif not re.fullmatch(r'[A-Za-z0-9_]+_test', name):
        raise ValueError('This rehearsal requires a separate database ending in _test; live databases are refused.')


def constraint_roles(connection):
    clause = connection.execute(text('''SELECT CHECK_CLAUSE
        FROM information_schema.CHECK_CONSTRAINTS
        WHERE CONSTRAINT_SCHEMA = DATABASE() AND CONSTRAINT_NAME = 'ck_user_role'
        AND TABLE_NAME = 'users' ''')).scalar_one()
    match = re.fullmatch(r"`?role`?\s+in\s*\(\s*('[a-z]+'(?:\s*,\s*'[a-z]+')*)\s*\)", clause.strip(), re.IGNORECASE)
    if not match:
        raise RuntimeError('The existing role constraint is unfamiliar; no automatic replacement is safe.')
    roles = set(re.findall(r"'([^']+)'", match.group(1)))
    if not roles <= set(TRANSITION_ROLES):
        raise RuntimeError('The role constraint contains an unexpected role.')
    return roles


def replace_constraint(connection, roles):
    # All identifiers and role literals here are fixed migration constants.
    literals = ','.join("'" + role + "'" for role in roles)
    connection.exec_driver_sql('ALTER TABLE users DROP CONSTRAINT ck_user_role, '
                              'ADD CONSTRAINT ck_user_role CHECK (role IN (' + literals + '))')
    connection.commit()


def migrate_roles(engine, *, expected_database=None):
    validate_target(engine, expected_database)
    lock_name = 'hf_roles_' + hashlib.sha256(engine.url.database.encode()).hexdigest()[:32]
    with engine.connect() as connection:
        if 'MariaDB' not in connection.exec_driver_sql('SELECT VERSION()').scalar_one():
            raise ValueError('This migration was written and tested for MariaDB.')
        if connection.execute(text('SELECT GET_LOCK(:name, 10)'), {'name': lock_name}).scalar_one() != 1:
            raise RuntimeError('Another role migration holds the migration lock.')
        connection.commit()
        try:
            before = [dict(row) for row in connection.exec_driver_sql('SELECT * FROM users ORDER BY id').mappings()]
            if any(row['role'] not in TRANSITION_ROLES for row in before):
                raise RuntimeError('An account has an unexpected role; no account was changed.')
            allowed = constraint_roles(connection)
            expected = [{**row, 'role': LEGACY_MAPPING.get(row['role'], row['role'])} for row in before]
            changed_ids = [old['id'] for old, new in zip(before, expected) if old['role'] != new['role']]
            connection.commit()
            if changed_ids or allowed != set(TARGET_ROLES):
                if allowed != set(TRANSITION_ROLES):
                    replace_constraint(connection, TRANSITION_ROLES)
                connection.exec_driver_sql("UPDATE users SET role = 'staff' WHERE role IN ('manager','cashier')")
                connection.commit()
                replace_constraint(connection, TARGET_ROLES)
            after = [dict(row) for row in connection.exec_driver_sql('SELECT * FROM users ORDER BY id').mappings()]
            if after != expected:
                raise RuntimeError('The account preservation check failed; inspect the test copy before proceeding.')
            if constraint_roles(connection) != set(TARGET_ROLES):
                raise RuntimeError('The final role constraint was not installed.')
            return {'migration': MIGRATION_ID, 'database': engine.url.database,
                    'status': 'applied' if changed_ids or allowed != set(TARGET_ROLES) else 'already_applied',
                    'changed_user_ids': changed_ids, 'accounts_preserved': len(after),
                    'counts_before': dict(Counter(row['role'] for row in before)),
                    'counts_after': dict(Counter(row['role'] for row in after)),
                    'passwords_emails_ids_customer_links_preserved': True,
                    'admin_accounts_created': 0}
        finally:
            connection.rollback()
            connection.execute(text('SELECT RELEASE_LOCK(:name)'), {'name': lock_name})
            connection.commit()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database-url-env', default='ROLE_MIGRATION_DATABASE_URL',
                        help='Environment variable containing the explicit test database URL.')
    args = parser.parse_args()
    url = os.environ.get(args.database_url_env)
    if not url:
        parser.error('Set the explicit test database URL; the live DATABASE_URL is never used by default.')
    engine = create_engine(url, pool_pre_ping=True)
    try:
        print(json.dumps(migrate_roles(engine), indent=2))
    finally:
        engine.dispose()


if __name__ == '__main__':
    main()
