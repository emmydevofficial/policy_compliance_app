"""Nigerian public holidays, for seeding the Holiday table.

Fixed-date and Easter-based holidays are computed. The Islamic holidays follow the lunar
calendar and are announced by the Federal Government shortly before; the dates here are
estimates and are marked so. The ADMIN should confirm them in the Reminder rules screen.
When a fixed holiday falls on a weekend the Government normally declares the next Monday a
holiday; those observed days are included.
"""

from datetime import date, timedelta

# Estimated (Eid-el-Fitr, Eid-el-Kabir, Eid-el-Maulud) dates by year.
ISLAMIC_ESTIMATES: dict[int, list[tuple[date, str]]] = {
    2025: [
        (date(2025, 3, 31), "Eid-el-Fitr (estimated)"),
        (date(2025, 4, 1), "Eid-el-Fitr holiday (estimated)"),
        (date(2025, 6, 6), "Eid-el-Kabir (estimated)"),
        (date(2025, 6, 9), "Eid-el-Kabir holiday (estimated)"),
        (date(2025, 9, 5), "Eid-el-Maulud (estimated)"),
    ],
    2026: [
        (date(2026, 3, 20), "Eid-el-Fitr (estimated)"),
        (date(2026, 3, 23), "Eid-el-Fitr holiday (estimated)"),
        (date(2026, 5, 27), "Eid-el-Kabir (estimated)"),
        (date(2026, 5, 28), "Eid-el-Kabir holiday (estimated)"),
        (date(2026, 8, 26), "Eid-el-Maulud (estimated)"),
    ],
    2027: [
        (date(2027, 3, 10), "Eid-el-Fitr (estimated)"),
        (date(2027, 3, 11), "Eid-el-Fitr holiday (estimated)"),
        (date(2027, 5, 17), "Eid-el-Kabir (estimated)"),
        (date(2027, 5, 18), "Eid-el-Kabir holiday (estimated)"),
        (date(2027, 8, 16), "Eid-el-Maulud (estimated)"),
    ],
    2028: [
        (date(2028, 2, 27), "Eid-el-Fitr (estimated)"),
        (date(2028, 2, 28), "Eid-el-Fitr holiday (estimated)"),
        (date(2028, 5, 5), "Eid-el-Kabir (estimated)"),
        (date(2028, 5, 8), "Eid-el-Kabir holiday (estimated)"),
        (date(2028, 8, 4), "Eid-el-Maulud (estimated)"),
    ],
}


def easter_sunday(year: int) -> date:
    """Anonymous Gregorian algorithm."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    ell = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * ell) // 451
    month, day = divmod(h + ell - 7 * m + 114, 31)
    return date(year, month, day + 1)


FIXED = [
    ((1, 1), "New Year's Day"),
    ((5, 1), "Workers' Day"),
    ((6, 12), "Democracy Day"),
    ((10, 1), "Independence Day"),
    ((12, 25), "Christmas Day"),
    ((12, 26), "Boxing Day"),
]


def nigerian_holidays(year: int) -> list[tuple[date, str]]:
    days: dict[date, str] = {}
    for (m, d), name in FIXED:
        days[date(year, m, d)] = name
    easter = easter_sunday(year)
    days[easter - timedelta(days=2)] = "Good Friday"
    days[easter + timedelta(days=1)] = "Easter Monday"
    for d, name in ISLAMIC_ESTIMATES.get(year, []):
        days.setdefault(d, name)
    # Observed days for fixed holidays falling on a weekend.
    for (m, dd), name in FIXED:
        d = date(year, m, dd)
        if d.weekday() >= 5:
            observed = d + timedelta(days=7 - d.weekday())
            while observed in days:
                observed += timedelta(days=1)
            days[observed] = f"{name} (observed)"
    return sorted(days.items())
