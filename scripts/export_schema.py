"""Export reproducible SQL DDL and Mongo validators without querying live data."""
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from sqlalchemy.dialects import mysql
from sqlalchemy.schema import CreateIndex, CreateTable
from app.db import Base
from app import models
from app.sql_views import VIEW_QUERIES
from app.mongo import REVIEW_SCHEMA, PROFILE_SCHEMA, EXTERNAL_REVIEW_SCHEMA

def main():
    dialect=mysql.dialect(paramstyle='named')
    statements=['-- Generated from app/models.py. Twelve operational InnoDB tables.\n-- Use an empty MariaDB schema; normal setup is scripts/seed.py.']
    for table in Base.metadata.sorted_tables:
        statements.append(str(CreateTable(table).compile(dialect=dialect)).strip()+';')
        for index in sorted(table.indexes,key=lambda i:i.name):
            statements.append(str(CreateIndex(index).compile(dialect=dialect)).strip()+';')
    for name, query in VIEW_QUERIES.items():
        statements.append('CREATE OR REPLACE VIEW '+name+' AS '+query.strip()+';')
    (ROOT/'data/schema.sql').write_text('\n\n'.join(statements)+'\n')
    validators={name:{'$jsonSchema':schema} for name,schema in [('reviews',REVIEW_SCHEMA),('customer_profiles',PROFILE_SCHEMA),('external_review_examples',EXTERNAL_REVIEW_SCHEMA)]}
    (ROOT/'data/mongo_validators.json').write_text(json.dumps(validators,indent=2)+'\n')
    print('Exported',len(Base.metadata.tables),'SQL tables,',len(VIEW_QUERIES),'views and',len(validators),'Mongo validators')

if __name__=='__main__': main()
