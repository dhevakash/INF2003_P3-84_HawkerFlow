"""Explainable SQL analytics: completed orders, recorded consumption, fixed RFM rules.

All time windows use [start, end), at UTC midnight (the operational store uses UTC).
Forecast stock is a live snapshot, not reconstructed historical inventory. Sales
averages include days with zero sales; they are estimates, not a trained ML model.
"""
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from sqlalchemy import case, func, literal, select, union_all
from app.models import Branch, BranchStock, Customer, Ingredient, MenuItem, Order, OrderLine, StockMovement
from app.sql_service import BusinessError


def midnight(day):
    return datetime.combine(day, time.min)


def validate_branch(session, branch_id):
    if branch_id is not None and session.get(Branch, branch_id) is None:
        raise BusinessError(404, "Branch not found")


def numeric(value, places=2):
    return round(float(value or 0), places)


def subtract_days(day, days):
    try:
        return day - timedelta(days=days)
    except OverflowError as error:
        raise BusinessError(422, "Date is too early for the requested comparison window") from error


def percentage(current, previous):
    return round((float(current) - float(previous)) / float(previous) * 100, 2) if previous else None


def order_period(start, end, branch_id):
    query = select(Order.id, Order.branch_id, Order.customer_id, Order.created_at, Order.total).where(
        Order.status == "completed", Order.created_at >= midnight(start), Order.created_at < midnight(end))
    return query.where(Order.branch_id == branch_id) if branch_id is not None else query


def dashboard(session, start: date, end: date, branch_id=None):
    if not 0 < (end - start).days <= 366:
        raise BusinessError(422, "Choose a positive date range of at most 366 days")
    validate_branch(session, branch_id)
    previous_start = subtract_days(start, (end - start).days)
    current = order_period(start, end, branch_id).cte("current_orders")
    previous = order_period(previous_start, start, branch_id).cte("previous_orders")
    totals = session.execute(select(func.count(current.c.id), func.coalesce(func.sum(current.c.total), 0))).one()
    previous_total = session.scalar(select(func.coalesce(func.sum(previous.c.total), 0)))
    branch_query = select(Branch.id, Branch.name, func.count(current.c.id).label("orders"),
                          func.coalesce(func.sum(current.c.total), 0).label("net_revenue")).outerjoin(
        current, Branch.id == current.c.branch_id).group_by(Branch.id, Branch.name).order_by(Branch.id)
    if branch_id is not None:
        branch_query = branch_query.where(Branch.id == branch_id)
    branches = [{"branch_id": row.id, "name": row.name, "orders": row.orders,
                 "net_revenue": numeric(row.net_revenue)} for row in session.execute(branch_query)]
    current_lines = select(OrderLine.menu_item_id,
                           func.sum(OrderLine.quantity).label("quantity"),
                           func.sum(OrderLine.quantity * OrderLine.unit_price).label("gross_sales")).join(
        current, OrderLine.order_id == current.c.id).group_by(OrderLine.menu_item_id).cte("current_menu")
    previous_lines = select(OrderLine.menu_item_id, func.sum(OrderLine.quantity).label("quantity")).join(
        previous, OrderLine.order_id == previous.c.id).group_by(OrderLine.menu_item_id).cte("previous_menu")
    quantity = func.coalesce(current_lines.c.quantity, 0)
    menu_query = select(MenuItem.id, MenuItem.name, quantity.label("quantity"),
                        func.coalesce(current_lines.c.gross_sales, 0).label("gross_sales"),
                        func.dense_rank().over(order_by=quantity.desc()).label("rank"),
                        func.coalesce(previous_lines.c.quantity, 0).label("previous_quantity")).outerjoin(
        current_lines, MenuItem.id == current_lines.c.menu_item_id).outerjoin(
        previous_lines, MenuItem.id == previous_lines.c.menu_item_id).order_by(quantity.desc(), MenuItem.id)
    menu = [{"menu_item_id": row.id, "name": row.name, "quantity": int(row.quantity),
             "gross_sales": numeric(row.gross_sales), "rank": row.rank,
             "previous_quantity": int(row.previous_quantity),
             "quantity_change_pct": percentage(row.quantity, row.previous_quantity)} for row in session.execute(menu_query)]
    # DATE and EXTRACT compile for MariaDB and SQLite; totals never join order lines.
    hour = func.extract("hour", current.c.created_at)
    hours = [{"hour": int(row.hour), "orders": row.orders, "net_revenue": numeric(row.net_revenue)}
             for row in session.execute(select(hour.label("hour"), func.count().label("orders"),
                                              func.sum(current.c.total).label("net_revenue")).group_by(hour).order_by(hour))]
    day = func.date(current.c.created_at)
    daily_rows = {str(row.day): {"date": str(row.day), "orders": row.orders, "net_revenue": numeric(row.net_revenue)}
                  for row in session.execute(select(day.label("day"), func.count().label("orders"),
                                                   func.sum(current.c.total).label("net_revenue")).group_by(day))}
    daily = [daily_rows.get((start + timedelta(days=n)).isoformat(), {
        "date": (start + timedelta(days=n)).isoformat(), "orders": 0, "net_revenue": 0.0}) for n in range((end-start).days)]
    return {"start": start.isoformat(), "end": end.isoformat(), "timezone": "UTC", "branch_id": branch_id,
            "summary": {"net_revenue": numeric(totals[1]), "orders": totals[0],
                        "average_order_value": numeric(totals[1] / totals[0]) if totals[0] else 0.0,
                        "previous_net_revenue": numeric(previous_total),
                        "revenue_change_pct": percentage(totals[1], previous_total)},
            "branches": branches, "menu": menu, "peak_hours": hours, "daily": daily,
            "underperforming": sorted([row for row in menu if row["previous_quantity"] > row["quantity"]],
                                      key=lambda row: (row["quantity_change_pct"], row["menu_item_id"]))}


def forecast(session, branch_id, as_of: date, window_days=28, target_days=7, lead_days=2):
    if not 1 <= window_days <= 365 or not 1 <= target_days <= 90 or not 0 <= lead_days <= 90:
        raise BusinessError(422, "Invalid forecast window or coverage days")
    validate_branch(session, branch_id)
    start = subtract_days(as_of, window_days)
    daily_usage = select(StockMovement.ingredient_id, func.date(StockMovement.created_at).label("day"),
                         func.sum(-StockMovement.quantity_delta).label("usage")).where(
        StockMovement.branch_id == branch_id, StockMovement.reason == "sale", StockMovement.quantity_delta < 0,
        StockMovement.created_at >= midnight(start), StockMovement.created_at < midnight(as_of)).group_by(
        StockMovement.ingredient_id, func.date(StockMovement.created_at)).cte("recorded_daily_usage")
    # A calendar CTE makes zero-sales days real rows before the window function.
    dates = [select(literal((start + timedelta(days=n)).isoformat()).label("day")) for n in range(window_days)]
    calendar = union_all(*dates).cte("calendar") if len(dates) > 1 else dates[0].cte("calendar")
    grid = select(BranchStock.ingredient_id, calendar.c.day, func.coalesce(daily_usage.c.usage, 0).label("usage")).select_from(
        BranchStock).join(calendar, literal(True)).outerjoin(daily_usage,
        (daily_usage.c.ingredient_id == BranchStock.ingredient_id) & (daily_usage.c.day == calendar.c.day)).where(
        BranchStock.branch_id == branch_id).cte("zero_filled_usage")
    rolling = func.avg(grid.c.usage).over(partition_by=grid.c.ingredient_id, order_by=grid.c.day, rows=(-6, 0))
    trend = [{"ingredient_id": row.ingredient_id, "date": row.day, "usage": numeric(row.usage, 4),
              "rolling_average": numeric(row.rolling_average, 4)} for row in session.execute(
        select(grid, rolling.label("rolling_average")).order_by(grid.c.ingredient_id, grid.c.day))]
    demand = select(daily_usage.c.ingredient_id, func.sum(daily_usage.c.usage).label("total_usage")).group_by(
        daily_usage.c.ingredient_id).cte("window_consumption")
    stocks = session.execute(select(Ingredient.id, Ingredient.name, Ingredient.unit, BranchStock.quantity,
                                    func.coalesce(demand.c.total_usage, 0).label("total_usage")).join(
        BranchStock, Ingredient.id == BranchStock.ingredient_id).outerjoin(demand, demand.c.ingredient_id == Ingredient.id).where(
        BranchStock.branch_id == branch_id).order_by(Ingredient.id)).all()
    from app.sql_service import business_today, sellable_stock_quantities
    stock_as_of = business_today()
    usable = sellable_stock_quantities(session, branch_id, as_of=stock_as_of)
    ingredients = []
    for stock in stocks:
        average = Decimal(str(stock.total_usage)) / window_days
        quantity = usable.get(stock.id, Decimal("0"))
        remaining = quantity / average if average else None
        risk = "out_of_stock" if quantity <= 0 else "insufficient_history" if remaining is None else "critical" if remaining <= lead_days else "restock" if remaining < target_days + lead_days else "healthy"
        ingredients.append({"ingredient_id": stock.id, "name": stock.name, "unit": stock.unit,
                            "quantity": numeric(stock.quantity, 4), "usable_quantity": numeric(quantity, 4),
                            "average_daily_usage": numeric(average, 4),
                            "days_remaining": numeric(remaining, 2) if remaining is not None else None,
                            "recommended_restock": numeric(max(Decimal("0"), average * (target_days + lead_days) - quantity), 4) if average else 0.0,
                            "risk": risk, "data_status": "observed_sales" if average else "insufficient_history"})
    return {"as_of": as_of.isoformat(), "window_days": window_days, "target_days": target_days,
            "lead_days": lead_days, "history_days": window_days, "branch_id": branch_id, "timezone": "UTC",
            "stock_basis": "current_snapshot", "stock_as_of": stock_as_of.isoformat(), "ingredients": ingredients, "daily": trend}


def loyalty_insights(session, as_of: date, window_days=90, branch_id=None):
    if not 1 <= window_days <= 365:
        raise BusinessError(422, "Choose a loyalty window from 1 to 365 days")
    validate_branch(session, branch_id)
    recent = order_period(subtract_days(as_of, window_days), as_of, branch_id).cte("recent_orders")
    history = select(Order.customer_id, func.max(Order.created_at).label("last_order")).where(
        Order.status == "completed", Order.created_at < midnight(as_of))
    if branch_id is not None:
        history = history.where(Order.branch_id == branch_id)
    history = history.group_by(Order.customer_id).cte("customer_history")
    spending = select(recent.c.customer_id, func.count().label("frequency"), func.sum(recent.c.total).label("monetary_value")).group_by(
        recent.c.customer_id).cte("recent_customer_spend")
    # Dialect-specific date difference stays in SQL, with identical UTC-day semantics.
    last_day = func.date(history.c.last_order)
    days = (func.julianday(as_of.isoformat()) - func.julianday(last_day)) if session.get_bind().dialect.name == "sqlite" else func.datediff(as_of, last_day)
    frequency = func.coalesce(spending.c.frequency, 0)
    monetary = func.coalesce(spending.c.monetary_value, 0)
    base = select(Customer.id.label("customer_id"), Customer.name, days.label("recency_days"),
                  frequency.label("frequency"), monetary.label("monetary_value"),
                  case((days <= 7, 5), (days <= 14, 4), (days <= 30, 3), (days <= 60, 2), (days.is_not(None), 1), else_=0).label("r_score"),
                  case((frequency >= 10, 5), (frequency >= 6, 4), (frequency >= 3, 3), (frequency >= 1, 2), else_=0).label("f_score"),
                  case((monetary >= 100, 5), (monetary >= 50, 4), (monetary >= 20, 3), (monetary > 0, 2), else_=0).label("m_score")).outerjoin(
        history, Customer.id == history.c.customer_id).outerjoin(spending, Customer.id == spending.c.customer_id).cte("rfm_scores")
    segment = case((base.c.recency_days.is_(None), "No orders"), (base.c.frequency == 0, "Dormant"),
                   (base.c.recency_days > 30, "At risk"),
                   ((base.c.r_score >= 4) & (base.c.f_score >= 4) & (base.c.m_score >= 4), "Champions"),
                   (base.c.f_score >= 3, "Loyal"), (base.c.m_score >= 4, "Big spenders"), else_="Recent customers")
    classified = select(base, segment.label("segment")).cte("classified_customers")
    customers = [{**dict(row), "recency_days": int(row["recency_days"]) if row["recency_days"] is not None else None,
                  "monetary_value": numeric(row["monetary_value"])} for row in session.execute(select(classified).order_by(classified.c.customer_id)).mappings()]
    segments = [{"segment": row.segment, "customers": row.customers} for row in session.execute(
        select(classified.c.segment, func.count().label("customers")).group_by(classified.c.segment).order_by(classified.c.segment))]
    return {"as_of": as_of.isoformat(), "window_days": window_days, "branch_id": branch_id, "timezone": "UTC",
            "customers": customers, "segments": segments,
            "scoring": {"recency_days": [7, 14, 30, 60], "frequency": [1, 3, 6, 10], "monetary_sgd": [0, 20, 50, 100]}}
