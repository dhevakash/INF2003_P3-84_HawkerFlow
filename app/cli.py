"""Explicit setup commands; importing the web app never destroys or seeds data."""
import argparse
import csv
from getpass import getpass, GetPassWarning
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import random
import warnings
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.schema import CreateIndex, CreateTable
from sqlalchemy.dialects import mysql
from app.analytics import initialize_views
from app.auth import hash_password
from app.config import ROOT
from app.database import Base, SessionLocal, engine
from app.models import (Branch, BranchStock, Customer, Ingredient, MenuItem, Order,
                        RecipeComponent, StockMovement, StockReceipt, User)
from app.nosql import initialize_mongo, mongo_db
from app.schemas import CheckoutInput, InitialAdminInput
from app.services.accounts import AccountSetupError, bootstrap_admin
from app.services.checkout import checkout


def seed_sql():
    rng = random.Random(20261002)
    with SessionLocal.begin() as session:
        existing = session.scalar(select(Branch).order_by(Branch.id))
        if existing and existing.name != 'HawkerFlow Demo 1':
            raise RuntimeError('Seed expects a dedicated empty/demo database. No existing data was changed.')
        if not existing:
            with (ROOT / 'data/raw/nea_hawker_centres.csv').open(newline='', encoding='utf-8-sig') as stream:
                locations = list(csv.DictReader(stream))[:5]
            session.add_all([Branch(id=i, name=f'HawkerFlow Demo {i}', address=row['location_of_centre'],
                source_label='fictional branch; address from historical NEA snapshot') for i, row in enumerate(locations, 1)])
            customers = [Customer(id=i, name=f'Customer {i}', email=f'customer{i}@hawkerflow.local') for i in range(1, 51)]
            session.add_all(customers)
            session.flush()
            password = hash_password('DemoPass123!')
            session.add_all([User(email='manager@hawkerflow.local', password_hash=password, role='staff'),
                User(email='cashier@hawkerflow.local', password_hash=password, role='staff')])
            session.add_all([User(email=c.email, password_hash=password, role='customer', customer_id=i)
                            for i, c in enumerate(customers, 1)])
            session.flush()
            actor_user_id = session.scalar(select(User.id).where(User.email == 'manager@hawkerflow.local'))
            ingredients = ['Rice', 'Chicken', 'Noodles', 'Tofu', 'Egg mixture', 'Cabbage', 'Carrot', 'Fish',
                           'Beef', 'Onion', 'Garlic', 'Chilli', 'Oil', 'Soy sauce', 'Spice mix']
            session.add_all([Ingredient(id=i, name=name, unit='g') for i, name in enumerate(ingredients, 1)])
            session.add_all([MenuItem(id=i, name=f'Demo Meal {i:02d}', price=Decimal('3.50') + Decimal(i) / 2)
                            for i in range(1, 21)])
            session.flush()
            for item_id in range(1, 21):
                for ingredient_id in rng.sample(range(1, 16), 3):
                    session.add(RecipeComponent(menu_item_id=item_id, ingredient_id=ingredient_id,
                                                quantity=Decimal(rng.randrange(20, 151))))
            for branch_id in range(1, 6):
                for ingredient_id in range(1, 16):
                    quantity = Decimal('500000.000')
                    session.add(BranchStock(branch_id=branch_id, ingredient_id=ingredient_id, quantity=quantity))
                    receipt = StockReceipt(branch_id=branch_id, ingredient_id=ingredient_id, quantity=quantity,
                                           actor_user_id=actor_user_id, note='Synthetic opening inventory; all quantities in grams',
                                           created_at=datetime(2026, 7, 1))
                    session.add(receipt)
                    session.flush()
                    session.add(StockMovement(branch_id=branch_id, ingredient_id=ingredient_id,
                                              delta=quantity, receipt_id=receipt.id, created_at=receipt.created_at))
        actor = session.scalar(select(User).where(User.email == 'manager@hawkerflow.local'))
        if actor is None or actor.role not in {'admin', 'staff'}:
            raise RuntimeError('The operational demo account is missing or still needs the role migration.')
        actor_user_id = actor.id
    rng = random.Random(20261003)
    for number in range(1, 201):
        payload = CheckoutInput(request_key=f'seed-order-{number:06d}', branch_id=rng.randrange(1, 6),
            customer_id=rng.randrange(1, 51), lines=[{'menu_item_id': rng.randrange(1, 21), 'quantity': rng.randrange(1, 4)}])
        timestamp = datetime(2026, 10, 1, 12) - timedelta(days=rng.randrange(90))
        with SessionLocal() as session:
            checkout(session, payload, actor_user_id, created_at=timestamp)
    with SessionLocal() as session:
        print({table.__tablename__: session.scalar(select(func.count()).select_from(table))
               for table in [Branch, Customer, MenuItem, Ingredient, Order]})


def seed_mongo():
    db = mongo_db()
    with SessionLocal() as session:
        orders = list(session.scalars(select(Order).where(Order.request_key.like('seed-order-%')).order_by(Order.id).limit(40)))
    for index, order in enumerate(orders):
        rating = index % 5 + 1
        db.reviews.update_one({'order_id': order.id}, {'$setOnInsert': {
            'customer_id': order.customer_id, 'branch_id': order.branch_id, 'rating': rating,
            'text': 'Synthetic demo feedback: ' + ('long wait at lunch' if rating <= 2 else 'tasty meal and friendly service'),
            'tags': ['waiting-time', 'service'] if rating <= 2 else ['food'],
            'category_ratings': {'food': rating}, 'replies': [], 'source': 'synthetic_purchase',
            'created_at': order.created_at.replace(tzinfo=timezone.utc)}}, upsert=True)
    for customer_id in range(1, 51):
        db.profiles.update_one({'customer_id': customer_id}, {'$setOnInsert': {
            'dietary_preferences': [], 'favourite_tags': ['food']}}, upsert=True)
    print({'reviews': db.reviews.count_documents({}), 'profiles': db.profiles.count_documents({})})


def import_uci(path):
    # The supplied UCI readme is not the dataset. Require the actual Yelp sentences.
    path = Path(path)
    if not path.is_file():
        raise RuntimeError('Supply the downloaded yelp_labelled.txt file. The readme alone cannot be imported.')
    records = []
    for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
        sentence, label = line.rsplit('\t', 1)
        if label not in {'0', '1'}:
            raise ValueError(f'Invalid binary label at row {number}')
        records.append({'source': 'UCI_YELP', 'source_row': number, 'text': sentence, 'sentiment': int(label)})
    if len(records) != 1000:
        raise ValueError(f'Expected the 1,000-row Yelp subset, found {len(records)}. Verify the source file.')
    db = mongo_db()
    for record in records:
        db.external_examples.update_one({'source': record['source'], 'source_row': record['source_row']}, {'$set': record}, upsert=True)
    print({'external_examples_imported': len(records)})


def admin_credentials(email):
    supplied_email = email if email is not None else input('Initial Admin email: ')
    # An explicit environment variable supports unattended local provisioning.
    # Interactive use never echoes a password or accepts it as a command argument.
    password = os.environ.get('HAWKERFLOW_INITIAL_ADMIN_PASSWORD')
    if password is None:
        with warnings.catch_warnings():
            warnings.simplefilter('error', GetPassWarning)
            password = getpass('Initial Admin password (12-128 characters): ')
            confirmation = getpass('Confirm initial Admin password: ')
        if password != confirmation:
            raise AccountSetupError('Passwords do not match. No Admin was created.')
    try:
        return InitialAdminInput(email=supplied_email, password=password)
    except ValidationError:
        # Do not print validation inputs, which can contain the supplied secret.
        raise AccountSetupError('Use a valid email and a nonblank password of 12-128 characters.') from None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['init-db', 'init-admin', 'seed', 'export-schema', 'import-uci'])
    parser.add_argument('--sql-only', action='store_true', help='SQLite/local SQL preview only; not a complete DBMS demo')
    parser.add_argument('--file', help='Path to the real yelp_labelled.txt for import-uci')
    parser.add_argument('--email', help='Initial Admin email for init-admin; prompts if omitted')
    args = parser.parse_args()
    if args.email is not None and args.command != 'init-admin':
        parser.error('--email is only supported by init-admin')
    if args.command == 'init-db':
        Base.metadata.create_all(engine)
        initialize_views(engine)
        if not args.sql_only:
            initialize_mongo()
        print('Schema and views initialized.' + (' SQL preview only.' if args.sql_only else ' MongoDB validators and indexes initialized.'))
    elif args.command == 'init-admin':
        try:
            result = bootstrap_admin(engine, lambda: admin_credentials(args.email))
        except (AccountSetupError, EOFError, GetPassWarning):
            parser.exit(1, 'Admin setup stopped. Check the role migration, an unused email and a matching '
                        '12-128 character password. Use an interactive terminal for hidden password entry.\n')
        if result.created:
            print(f'Initial Admin created (account ID {result.account_id}). Sign in with the supplied credentials.')
        else:
            print(f'An Admin already exists (account ID {result.account_id}); no account or password was changed.')
    elif args.command == 'seed':
        seed_sql()
        if not args.sql_only:
            seed_mongo()
    elif args.command == 'export-schema':
        target = ROOT / 'database/sql/schema.generated.sql'
        schema = ('-- Generated from app/models.py. Do not hand-edit; regenerate instead.\n\n' +
            '\n\n'.join(str(CreateTable(t).compile(dialect=mysql.dialect())) + ';' for t in Base.metadata.sorted_tables) +
            '\n\n' + '\n'.join(str(CreateIndex(index).compile(dialect=mysql.dialect())) + ';'
                for table in Base.metadata.sorted_tables for index in sorted(table.indexes, key=lambda i:i.name)))
        target.write_text('\n'.join(line.rstrip() for line in schema.splitlines()) + '\n', encoding='utf-8')
        print(target)
    elif args.command == 'import-uci':
        if not args.file:
            parser.error('import-uci requires --file path/to/yelp_labelled.txt')
        import_uci(args.file)


if __name__ == '__main__':
    main()
