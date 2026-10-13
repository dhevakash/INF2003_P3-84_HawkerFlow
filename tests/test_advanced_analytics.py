"""Known-result analytics tests, independent of production database services."""
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db import Base, get_session
from app.models import Branch, BranchStock, Customer, Ingredient, MenuItem, Order, OrderLine, StockMovement, StockBatch
from app.advanced_analytics import dashboard, forecast, loyalty_insights
from app.advanced_routes import router
from app.security import current_user
from app.sql_service import BusinessError


@pytest.fixture
def factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'analytics.sqlite'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as session:
        session.add_all([Branch(id=1, name="One", address="A", postal_code="123456"),
                         Branch(id=2, name="Two", address="B", postal_code="654321"),
                         Customer(id=1, name="Regular", email="regular@test.test"),
                         Customer(id=2, name="Never ordered", email="new@test.test"),
                         Customer(id=3, name="Dormant", email="dormant@test.test"),
                         Ingredient(id=1, name="Rice", unit="kg"), Ingredient(id=2, name="Chicken", unit="kg"),
                         MenuItem(id=1, name="Rice Bowl", category="Meals", price=5),
                         MenuItem(id=2, name="Chicken Rice", category="Meals", price=10)])
        session.flush()
        session.add_all([BranchStock(branch_id=1, ingredient_id=1, quantity=6, reorder_level=1),
                         BranchStock(branch_id=1, ingredient_id=2, quantity=10, reorder_level=1)])
        session.commit()
    yield factory
    engine.dispose()


def add_order(session, order_id, customer, timestamp, total, branch=1, lines=()):
    session.add(Order(id=order_id, customer_id=customer, branch_id=branch, created_at=timestamp,
                      status="completed", total=total, request_key=f"analytics-{order_id}"))
    session.flush()
    session.add_all([OrderLine(order_id=order_id, menu_item_id=menu, quantity=quantity, unit_price=price)
                     for menu, quantity, price in lines])


def test_dashboard_net_revenue_no_line_fanout_and_equal_previous_period(factory):
    with factory() as session:
        add_order(session, 1, 1, datetime(2026, 10, 1, 12), 24, lines=[(1, 1, 5), (2, 2, 10)])
        add_order(session, 2, 1, datetime(2026, 9, 30, 12), 10, lines=[(2, 1, 10)])
        add_order(session, 3, 1, datetime(2026, 10, 2), 100, branch=2, lines=[(1, 20, 5)])
        session.commit()
        result = dashboard(session, date(2026, 10, 1), date(2026, 10, 2))
        assert result["summary"] == {"net_revenue": 24.0, "orders": 1, "average_order_value": 24.0,
                                      "previous_net_revenue": 10.0, "revenue_change_pct": 140.0}
        assert result["branches"][1]["orders"] == 0
        assert result["menu"][0]["name"] == "Chicken Rice"
        assert result["menu"][0]["quantity_change_pct"] == 100
        assert sum(row["gross_sales"] for row in result["menu"]) == 25
        assert result["peak_hours"] == [{"hour": 12, "orders": 1, "net_revenue": 24.0}]
        assert dashboard(session, date(2026, 10, 2), date(2026, 10, 3), 1)["summary"]["orders"] == 0


def test_dashboard_zero_days_ranks_and_declines(factory):
    with factory() as session:
        add_order(session, 1, 1, datetime(2026, 9, 29), 20, lines=[(1, 4, 5)])
        add_order(session, 2, 1, datetime(2026, 10, 1), 15, lines=[(1, 1, 5), (2, 1, 10)])
        session.commit()
        result = dashboard(session, date(2026, 10, 1), date(2026, 10, 3))
        assert [row["rank"] for row in result["menu"]] == [1, 1]
        assert result["underperforming"][0]["quantity_change_pct"] == -75
        assert result["daily"][1] == {"date": "2026-10-02", "orders": 0, "net_revenue": 0.0}


def test_forecast_recorded_consumption_zero_days_and_expired_stock(factory, monkeypatch):
    monkeypatch.setattr("app.sql_service.business_today", lambda: date(2026, 10, 13))
    with factory() as session:
        session.add_all([StockMovement(branch_id=1, ingredient_id=1, quantity_delta=-4, reason="sale", created_at=datetime(2026, 10, 11)),
                         StockMovement(branch_id=1, ingredient_id=1, quantity_delta=-99, reason="expired_discard", created_at=datetime(2026, 10, 11)),
                         StockMovement(branch_id=2, ingredient_id=1, quantity_delta=-99, reason="sale", created_at=datetime(2026, 10, 11)),
                         StockMovement(branch_id=1, ingredient_id=1, quantity_delta=-99, reason="sale", created_at=datetime(2026, 10, 13)),
                         StockBatch(branch_id=1, ingredient_id=1, initial_quantity=2, remaining_quantity=2,
                                    expires_on=date(2026, 10, 12), source="receipt"),
                         StockBatch(branch_id=1, ingredient_id=1, initial_quantity=3, remaining_quantity=3,
                                    expires_on=date(2026, 10, 13), source="receipt")])
        session.commit()
        result = forecast(session, 1, date(2026, 10, 13), window_days=4, target_days=7, lead_days=2)
        rice, chicken = result["ingredients"]
        assert rice["quantity"] == 6
        assert rice["usable_quantity"] == 4  # same-day batch + legacy remainder
        assert rice["average_daily_usage"] == 1  # 4 / four days, including three zero days
        assert rice["days_remaining"] == 4
        assert rice["recommended_restock"] == 5
        assert rice["risk"] == "restock"
        assert chicken["data_status"] == "insufficient_history"
        assert chicken["days_remaining"] is None
        rice_trend = [row for row in result["daily"] if row["ingredient_id"] == 1]
        assert [row["usage"] for row in rice_trend] == [0, 0, 4, 0]
        assert rice_trend[-1]["rolling_average"] == 1


def test_forecast_single_day_and_seven_day_window(factory):
    with factory() as session:
        session.add(StockMovement(branch_id=1, ingredient_id=1, quantity_delta=-8, reason="sale", created_at=datetime(2026, 10, 5)))
        session.commit()
        assert len(forecast(session, 1, date(2026, 10, 13), window_days=1)["daily"]) == 2
        result = forecast(session, 1, date(2026, 10, 13), window_days=8)
        assert result["ingredients"][0]["average_daily_usage"] == 1
        assert [row for row in result["daily"] if row["ingredient_id"] == 1][-1]["rolling_average"] == 0


def test_forecast_zero_stock_and_unknown_history_are_independent(factory):
    with factory() as session:
        session.get(BranchStock, (1, 2)).quantity = Decimal("0")
        session.commit()
        chicken = forecast(session, 1, date(2026, 10, 13))["ingredients"][1]
        assert chicken["risk"] == "out_of_stock"
        assert chicken["data_status"] == "insufficient_history"
        assert chicken["days_remaining"] is None
        assert chicken["recommended_restock"] == 0


def test_rfm_scores_segments_no_orders_and_branch_scope(factory):
    with factory() as session:
        for index in range(6):
            add_order(session, index + 1, 1, datetime(2026, 10, 12), 10)
        add_order(session, 7, 3, datetime(2026, 1, 1), 500)
        # As-of midnight is exclusive, and orders in other branches do not inflate RFM.
        add_order(session, 8, 1, datetime(2026, 10, 13), 1000)
        add_order(session, 9, 1, datetime(2026, 10, 12), 1000, branch=2)
        session.commit()
        result = loyalty_insights(session, date(2026, 10, 13), 90, 1)
        regular, new, dormant = result["customers"]
        assert (regular["recency_days"], regular["frequency"], regular["monetary_value"]) == (1, 6, 60)
        assert (regular["r_score"], regular["f_score"], regular["m_score"], regular["segment"]) == (5, 4, 4, "Champions")
        assert new["segment"] == "No orders" and new["recency_days"] is None
        assert dormant["segment"] == "Dormant" and dormant["frequency"] == 0
        assert sum(row["customers"] for row in result["segments"]) == 3


def test_empty_data_and_invalid_parameters(factory):
    with factory() as session:
        assert dashboard(session, date(2026, 10, 1), date(2026, 10, 2))["summary"]["revenue_change_pct"] is None
        assert all(row["segment"] == "No orders" for row in loyalty_insights(session, date(2026, 10, 13))["customers"])
        for call in [lambda: dashboard(session, date(2026, 10, 2), date(2026, 10, 1)),
                     lambda: forecast(session, 1, date(2026, 10, 13), 0),
                     lambda: loyalty_insights(session, date(2026, 10, 13), 0)]:
            with pytest.raises(BusinessError) as error:
                call()
            assert error.value.status_code == 422
        with pytest.raises(BusinessError) as error:
            dashboard(session, date(2026, 10, 1), date(2026, 10, 2), 99)
        assert error.value.status_code == 404


def test_manager_only_endpoints_and_http_validation(factory):
    app = FastAPI()
    app.include_router(router)
    user = {"role": "manager"}
    def sessions():
        with factory() as session:
            yield session
    app.dependency_overrides[get_session] = sessions
    app.dependency_overrides[current_user] = lambda: SimpleNamespace(**user)
    with TestClient(app) as client:
        paths = ["/api/analytics/dashboard?start=2026-10-01&end=2026-10-02",
                 "/api/analytics/forecast?branch_id=1&as_of=2026-10-13",
                 "/api/analytics/loyalty?as_of=2026-10-13"]
        assert all(client.get(path).status_code == 200 for path in paths)
        assert client.get("/api/analytics/dashboard?start=2026-10-02&end=2026-10-01").status_code == 422
        assert client.get("/api/analytics/forecast?branch_id=1&window_days=0").status_code == 422
        assert client.get("/api/analytics/forecast?branch_id=99").status_code == 404
        assert client.get("/api/analytics/forecast?branch_id=1&as_of=0001-01-01").status_code == 422
        for role in ("cashier", "customer"):
            user["role"] = role
            assert all(client.get(path).status_code == 403 for path in paths)
