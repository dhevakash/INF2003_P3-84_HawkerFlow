"""Opt-in MariaDB rehearsal tests; also runnable with Python's unittest runner."""
import importlib.util
import json
import os
from pathlib import Path
import unittest

from sqlalchemy import create_engine
from sqlalchemy.exc import DBAPIError


def load_migration():
    path = Path(os.getenv('ROLE_MIGRATION_SCRIPT', str(
        Path(__file__).resolve().parents[1] / 'database/migrations/001_admin_staff_customer.py')))
    spec = importlib.util.spec_from_file_location('account_role_migration_001', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MigrationTargetGuards(unittest.TestCase):
    def test_live_database_is_refused_before_connecting(self):
        migration = load_migration()
        engine = create_engine('mysql+pymysql://unused:unused@localhost/hawkerflow')
        try:
            with self.assertRaisesRegex(ValueError, 'live databases are refused'):
                migration.migrate_roles(engine)
        finally:
            engine.dispose()

    def test_sqlite_is_refused(self):
        migration = load_migration()
        engine = create_engine('sqlite:///:memory:')
        try:
            with self.assertRaisesRegex(ValueError, 'requires MariaDB'):
                migration.migrate_roles(engine)
        finally:
            engine.dispose()


@unittest.skipUnless(os.getenv('RUN_ROLE_MIGRATION_INTEGRATION') == '1',
                     'Set RUN_ROLE_MIGRATION_INTEGRATION=1 and ROLE_MIGRATION_DATABASE_URL for a test copy.')
class RoleMigrationRehearsal(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.migration = load_migration()
        cls.engine = create_engine(os.environ['ROLE_MIGRATION_DATABASE_URL'])
        cls.migration.validate_target(cls.engine)
        with cls.engine.connect() as connection:
            cls.before = [dict(row) for row in connection.exec_driver_sql('SELECT * FROM users ORDER BY id').mappings()]
            cls.orders_before = list(connection.exec_driver_sql('SELECT * FROM orders ORDER BY id'))
            cls.receipts_before = list(connection.exec_driver_sql('SELECT * FROM stock_receipts ORDER BY id'))
        if not cls.before:
            raise RuntimeError('Use a restored, populated test copy for this rehearsal.')
        cls.result = cls.migration.migrate_roles(cls.engine)
        report_path = os.getenv('ROLE_MIGRATION_RESULT')
        if report_path:
            Path(report_path).write_text(json.dumps(cls.result, indent=2), encoding='utf-8')

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()

    def test_accounts_change_only_their_role(self):
        expected = [{**row, 'role': self.migration.LEGACY_MAPPING.get(row['role'], row['role'])} for row in self.before]
        with self.engine.connect() as connection:
            actual = [dict(row) for row in connection.exec_driver_sql('SELECT * FROM users ORDER BY id').mappings()]
        # Avoid printing password hashes in an assertion diff.
        self.assertTrue(actual == expected, 'An account field other than its mapped role changed.')

    def test_historical_orders_and_receipts_unchanged(self):
        with self.engine.connect() as connection:
            self.assertTrue(list(connection.exec_driver_sql('SELECT * FROM orders ORDER BY id')) == self.orders_before)
            self.assertTrue(list(connection.exec_driver_sql('SELECT * FROM stock_receipts ORDER BY id')) == self.receipts_before)

    def test_initial_admin_is_not_implicitly_created(self):
        before = sum(row['role'] == 'admin' for row in self.before)
        with self.engine.connect() as connection:
            actual = connection.exec_driver_sql("SELECT COUNT(*) FROM users WHERE role='admin'").scalar_one()
        self.assertEqual(actual, before)

    def test_all_three_target_roles_are_accepted(self):
        for role in self.migration.TARGET_ROLES:
            with self.subTest(role=role), self.engine.connect() as connection:
                transaction = connection.begin()
                try:
                    connection.exec_driver_sql('UPDATE users SET role=%s WHERE id=%s', (role, self.before[0]['id']))
                finally:
                    transaction.rollback()

    def test_legacy_and_invalid_roles_are_rejected_by_database(self):
        for role in ('manager', 'cashier', 'owner', 'superuser', ''):
            with self.subTest(role=role), self.engine.connect() as connection:
                transaction = connection.begin()
                try:
                    with self.assertRaises(DBAPIError) as error:
                        connection.exec_driver_sql('UPDATE users SET role=%s WHERE id=%s', (role, self.before[0]['id']))
                    self.assertIn('ck_user_role', str(error.exception.orig))
                finally:
                    transaction.rollback()

    def test_repeated_migration_is_a_noop(self):
        result = self.migration.migrate_roles(self.engine)
        self.assertEqual(result['status'], 'already_applied')
        self.assertEqual(result['changed_user_ids'], [])
        self.assertEqual(result['accounts_preserved'], len(self.before))


if __name__ == '__main__':
    unittest.main(verbosity=2)
