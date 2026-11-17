"""Регрессионные тесты независимых rolling BS-периодов."""

from datetime import datetime, timedelta

import pytest

from app.xray.bs_limit import (
    aggregate_bs_usage_by_period,
    bs_reset_due,
    bs_usage_period,
    period_keys,
)


@pytest.mark.parametrize(
    ("strategy", "days"),
    [("day", 1), ("week", 7), ("month", 30), ("year", 365)],
)
def test_bs_reset_due_uses_same_rolling_boundaries_as_traffic(strategy, days):
    anchor = datetime(2026, 1, 1, 12, 0, 0)
    assert not bs_reset_due(strategy, anchor, None, anchor + timedelta(days=days) - timedelta(seconds=1))
    assert bs_reset_due(strategy, anchor, None, anchor + timedelta(days=days))


def test_bs_usage_period_is_stable_until_reset():
    anchor = datetime(2026, 1, 1, 12, 0, 0)
    assert bs_usage_period("day", anchor, None, anchor + timedelta(hours=23)) == "2026-01-01T12:00:00"
    assert bs_usage_period("year", anchor, None, anchor + timedelta(days=100)) == "2026-01-01T12:00:00"


def test_bs_usage_period_reads_legacy_month_without_anchor():
    now = datetime(2026, 6, 16, 13, 5)
    assert bs_usage_period("month", None, datetime(2020, 1, 1), now) == period_keys(now)


def test_aggregate_bs_usage_by_period_supports_mixed_users():
    rows = [
        {"user_id": 1, "monthly_used": 100, "monthly_period": "day-start"},
        {"user_id": 1, "monthly_used": 50, "monthly_period": "day-start"},
        {"user_id": 1, "monthly_used": 999, "monthly_period": "old"},
        {"user_id": 2, "monthly_used": 70, "monthly_period": "month-start"},
        {"user_id": 2, "monthly_used": 80, "monthly_period": "day-start"},
    ]
    assert aggregate_bs_usage_by_period(rows, {1: "day-start", 2: "month-start"}) == {1: 150, 2: 70}
