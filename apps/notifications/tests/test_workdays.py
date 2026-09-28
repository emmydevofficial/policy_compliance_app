from datetime import date

import pytest

from apps.notifications.models import Holiday
from apps.notifications.workdays import (
    add_working_days,
    is_working_day,
    next_working_day,
    working_days_between,
)


@pytest.fixture
def year_end(db):
    for d, n in [
        (date(2026, 12, 25), "Christmas"),
        (date(2026, 12, 26), "Boxing Day"),
        (date(2026, 12, 28), "Boxing Day (observed)"),
        (date(2027, 1, 1), "New Year"),
    ]:
        Holiday.objects.create(date=d, name=n)


def test_add_working_days_across_christmas(year_end):
    assert add_working_days(date(2026, 12, 24), 1) == date(2026, 12, 29)


def test_add_working_days_across_the_new_year(year_end):
    assert add_working_days(date(2026, 12, 31), 1) == date(2027, 1, 4)
    assert add_working_days(date(2026, 12, 24), 5) == date(2027, 1, 5)


def test_next_working_day_from_a_holiday_weekend(year_end):
    assert next_working_day(date(2026, 12, 25)) == date(2026, 12, 29)


def test_holiday_on_a_monday(db):
    Holiday.objects.create(date=date(2026, 10, 5), name="Monday holiday")
    assert not is_working_day(date(2026, 10, 5))
    assert add_working_days(date(2026, 10, 2), 1) == date(2026, 10, 6)
    assert next_working_day(date(2026, 10, 3)) == date(2026, 10, 6)
    assert working_days_between(date(2026, 10, 2), date(2026, 10, 7)) == 2


def test_negative_working_days(db):
    assert add_working_days(date(2026, 10, 5), -1) == date(2026, 10, 2)


def test_seeded_holidays_include_fixed_and_easter_days():
    from apps.notifications.holidays import easter_sunday, nigerian_holidays

    assert easter_sunday(2026) == date(2026, 4, 5)
    days = dict(nigerian_holidays(2026))
    assert days[date(2026, 10, 1)] == "Independence Day"
    assert days[date(2026, 4, 3)] == "Good Friday"
    assert days[date(2026, 4, 6)] == "Easter Monday"
    assert date(2026, 12, 28) in days  # Boxing Day falls on a Saturday; observed Monday
