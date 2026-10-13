"""Manager-only endpoints for explainable SQL analytics."""
from datetime import date, datetime, timezone
from fastapi import APIRouter, Query
from app.advanced_analytics import dashboard, forecast, loyalty_insights
from app.sql_routes import ManagerDep, SessionDep, invoke

router = APIRouter(prefix="/api/analytics", tags=["Advanced SQL analytics"])


def utc_today():
    return datetime.now(timezone.utc).date()


@router.get("/dashboard")
def get_dashboard(session: SessionDep, user: ManagerDep, start: date, end: date,
                  branch_id: int | None = Query(default=None, gt=0)):
    return invoke(dashboard, session, start, end, branch_id)


@router.get("/forecast")
def get_forecast(session: SessionDep, user: ManagerDep, branch_id: int = Query(gt=0),
                 as_of: date | None = None, window_days: int = Query(default=28, ge=1, le=365),
                 target_days: int = Query(default=7, ge=1, le=90), lead_days: int = Query(default=2, ge=0, le=90)):
    return invoke(forecast, session, branch_id, as_of or utc_today(), window_days, target_days, lead_days)


@router.get("/loyalty")
def get_loyalty_insights(session: SessionDep, user: ManagerDep, as_of: date | None = None,
                         window_days: int = Query(default=90, ge=1, le=365),
                         branch_id: int | None = Query(default=None, gt=0)):
    return invoke(loyalty_insights, session, as_of or utc_today(), window_days, branch_id)
