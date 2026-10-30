"""Matched, repeatable tag-count workload; measurements are generated only when run."""
import argparse
import json
from pathlib import Path
import platform
import random
import statistics
import sys
from time import perf_counter
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import Column, Index, Integer, MetaData, String, Table, insert, text
from app.database import engine
from app.nosql import mongo_db


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--rows', type=int, default=10000)
    parser.add_argument('--repetitions', type=int, default=20)
    args = parser.parse_args()
    if args.rows < 100 or args.repetitions < 5:
        parser.error('Use at least 100 rows and 5 repetitions.')
    if engine.dialect.name not in {'mysql', 'mariadb'}:
        parser.error('Benchmark requires real MariaDB and MongoDB; preview results are not comparable.')
    db = mongo_db()
    rng = random.Random(20261002)
    run_id = uuid.uuid4().hex
    docs = [{'run_id': run_id, 'review_id': i, 'rating': rng.randrange(1, 6),
             'tags': rng.sample(['food', 'service', 'waiting-time', 'value', 'cleanliness'], 2)}
            for i in range(args.rows)]
    metadata = MetaData()
    reviews = Table('benchmark_reviews', metadata,
        Column('run_id', String(32), primary_key=True), Column('review_id', Integer, primary_key=True),
        Column('rating', Integer, nullable=False), mysql_engine='InnoDB')
    tags = Table('benchmark_review_tags', metadata,
        Column('run_id', String(32), primary_key=True), Column('review_id', Integer, primary_key=True),
        Column('tag', String(40), primary_key=True), mysql_engine='InnoDB')
    Index('ix_benchmark_run_rating', reviews.c.run_id, reviews.c.rating)
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(insert(reviews), [{k:d[k] for k in ('run_id','review_id','rating')} for d in docs])
        connection.execute(insert(tags), [{'run_id':run_id,'review_id':d['review_id'],'tag':tag} for d in docs for tag in d['tags']])
    collection = db.benchmark_reviews
    collection.create_index([('run_id', 1), ('review_id', 1)], unique=True)
    collection.create_index([('run_id', 1), ('rating', 1), ('tags', 1)])
    collection.insert_many(docs)
    sql = '''SELECT t.tag, COUNT(*) AS count FROM benchmark_reviews r
        JOIN benchmark_review_tags t ON r.run_id=t.run_id AND r.review_id=t.review_id
        WHERE r.run_id=:run_id AND r.rating<=2 GROUP BY t.tag ORDER BY t.tag'''
    pipeline = [{'$match': {'run_id': run_id, 'rating': {'$lte': 2}}}, {'$unwind': '$tags'},
                {'$group': {'_id': '$tags', 'count': {'$sum': 1}}}, {'$sort': {'_id': 1}}]
    with engine.connect() as connection:
        def sql_query():
            return {r['tag']: r['count'] for r in connection.execute(text(sql), {'run_id': run_id}).mappings()}
        def mongo_query():
            return {r['_id']: r['count'] for r in collection.aggregate(pipeline)}
        expected = {}
        for d in docs:
            if d['rating'] <= 2:
                for tag in d['tags']:
                    expected[tag] = expected.get(tag, 0) + 1
        assert sql_query() == mongo_query() == expected, 'Results must agree before timing.'
        for _ in range(3): sql_query(); mongo_query()
        timings = {'sql_ms': [], 'mongo_ms': []}
        for i in range(args.repetitions):
            # Alternate order to reduce a consistent first-run/cache advantage.
            functions = [('sql_ms', sql_query), ('mongo_ms', mongo_query)]
            for key, function in (functions if i % 2 == 0 else reversed(functions)):
                start = perf_counter(); result = function(); elapsed = (perf_counter()-start)*1000
                assert result == expected
                timings[key].append(elapsed)
        sql_version = connection.execute(text('SELECT VERSION()')).scalar_one()
        plan = [dict(row._mapping) for row in connection.execute(text('EXPLAIN '+sql), {'run_id':run_id})]
    report = {'run_id':run_id,'rows':args.rows,'repetitions':args.repetitions,'seed':20261002,
        'python':sys.version,'platform':platform.platform(),'sql_version':sql_version,
        'mongo_version':db.client.server_info()['version'],'results':expected,'timings':timings,
        'median_ms':{k:statistics.median(v) for k,v in timings.items()},'sql_explain':plan,
        'scope':'Warm end-to-end client timings, including result materialization; one tag-count workload, not general DBMS superiority.'}
    target = Path(__file__).resolve().parents[1] / 'evidence' / f'benchmark_{run_id}.json'
    target.write_text(json.dumps(report, indent=2, default=str))
    print(target)
    print(json.dumps(report['median_ms'], indent=2))


if __name__ == '__main__':
    main()
