"""Visible SQL for assessment: views, joins, aggregates, nested query and window rank."""
from sqlalchemy import text

VIEWS = {
    'v_branch_sales': '''SELECT b.id AS branch_id, b.name AS branch,
        COUNT(o.id) AS orders, COALESCE(SUM(o.total), 0) AS revenue
        FROM branches b LEFT JOIN orders o ON o.branch_id = b.id
        GROUP BY b.id, b.name''',
    'v_item_sales': '''SELECT m.id AS menu_item_id, m.name,
        COALESCE(SUM(l.quantity), 0) AS units,
        COALESCE(SUM(l.quantity * l.unit_price), 0) AS gross_sales
        FROM menu_items m LEFT JOIN order_lines l ON l.menu_item_id = m.id
        GROUP BY m.id, m.name''',
}
RANKED_SALES = '''WITH totals AS (SELECT * FROM v_branch_sales)
    SELECT branch_id, branch, orders, revenue,
           DENSE_RANK() OVER (ORDER BY revenue DESC) AS revenue_rank
    FROM totals ORDER BY revenue_rank, branch_id'''
ABOVE_AVERAGE_CUSTOMERS = '''SELECT c.id, c.name, SUM(o.total) AS spend
    FROM customers c JOIN orders o ON o.customer_id = c.id
    GROUP BY c.id, c.name
    HAVING SUM(o.total) > (SELECT AVG(t.spend) FROM
        (SELECT SUM(total) AS spend FROM orders GROUP BY customer_id) t)
    ORDER BY spend DESC'''


def initialize_views(engine):
    with engine.begin() as connection:
        for name, query in VIEWS.items():
            connection.execute(text(f'DROP VIEW IF EXISTS {name}'))
            connection.execute(text(f'CREATE VIEW {name} AS {query}'))


def rows(session, sql, params=None):
    return [dict(row) for row in session.execute(text(sql), params or {}).mappings()]
