"""Read-only reporting views; revenue counts each completed order once.

These views intentionally contain no mutable financial ledger or trigger.
The revenue view is all-time; the sales endpoint applies an explicit date range.
"""
from sqlalchemy import text


VIEW_QUERIES = {
    "v_low_stock": """
SELECT stock.branch_id, branches.name AS branch_name,
       stock.ingredient_id, ingredients.name AS ingredient_name,
       ingredients.unit, stock.quantity, stock.reorder_level,
       stock.reorder_level - stock.quantity AS shortfall
FROM branch_stock AS stock
JOIN branches ON branches.id = stock.branch_id
JOIN ingredients ON ingredients.id = stock.ingredient_id
WHERE stock.quantity <= stock.reorder_level
""".strip(),
    "v_completed_branch_revenue": """
SELECT branches.id AS branch_id, branches.name AS branch_name,
       COUNT(orders.id) AS completed_orders,
       COALESCE(SUM(orders.total), 0) AS net_revenue,
       COALESCE(SUM(orders.points_redeemed), 0) AS points_redeemed
FROM branches
LEFT JOIN orders ON orders.branch_id = branches.id
                AND orders.status = 'completed'
GROUP BY branches.id, branches.name
""".strip(),
}


def create_views(engine):
    """Create/update the two application-owned views after table creation.

SQLite's DROP/CREATE branch is for unit tests only. MariaDB atomically replaces
each view without leaving it temporarily missing to concurrent readers.
"""
    with engine.begin() as connection:
        for name, query in VIEW_QUERIES.items():
            if engine.dialect.name == "sqlite":
                connection.execute(text(f"DROP VIEW IF EXISTS {name}"))
                connection.execute(text(f"CREATE VIEW {name} AS {query}"))
            else:
                connection.execute(text(f"CREATE OR REPLACE VIEW {name} AS {query}"))
