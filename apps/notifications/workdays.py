"""Working-day arithmetic. Every date calculation in the system uses these functions.

Weekends are Saturday and Sunday. Public holidays come from the Holiday table, never from a
hard-coded list.
"""

from collections.abc import Iterable
from datetime import date, timedelta


def _holidays(extra: Iterable[date] | None = None) -> set[date]:
    from .models import Holiday

    days = set(Holiday.objects.values_list("date", flat=True))
    if extra:
        days |= set(extra)
    return days


def is_working_day(d: date, holidays: set[date] | None = None) -> bool:
    holidays = _holidays() if holidays is None else holidays
    return d.weekday() < 5 and d not in holidays


def next_working_day(d: date, holidays: set[date] | None = None) -> date:
    """The first working day on or after d."""
    holidays = _holidays() if holidays is None else holidays
    while not is_working_day(d, holidays):
        d += timedelta(days=1)
    return d


def previous_working_day(d: date, holidays: set[date] | None = None) -> date:
    """The last working day on or before d."""
    holidays = _holidays() if holidays is None else holidays
    while not is_working_day(d, holidays):
        d -= timedelta(days=1)
    return d


def add_working_days(d: date, n: int, holidays: set[date] | None = None) -> date:
    """Move n working days from d (n may be negative). add_working_days(d, 0) is d itself
    if d is a working day, otherwise the next working day."""
    holidays = _holidays() if holidays is None else holidays
    if n == 0:
        return next_working_day(d, holidays)
    step = 1 if n > 0 else -1
    remaining = abs(n)
    while remaining:
        d += timedelta(days=step)
        if is_working_day(d, holidays):
            remaining -= 1
    return d


def working_days_between(start: date, end: date, holidays: set[date] | None = None) -> int:
    """Working days after start, up to and including end. Zero if end <= start."""
    holidays = _holidays() if holidays is None else holidays
    count = 0
    d = start
    while d < end:
        d += timedelta(days=1)
        if is_working_day(d, holidays):
            count += 1
    return count
