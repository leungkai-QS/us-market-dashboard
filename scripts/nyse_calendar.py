"""NYSE cash-session calendar.

Dates follow the NYSE Group holiday and early-close notice for 2026–2028:
https://www.nyse.com/trade/hours-calendars/

A date is a trading day unless it is a weekend or a full close. Early-close
days are trading days; the cash session ends at 13:00 ET instead of 16:00 ET.
Extend HOLIDAYS and EARLY_CLOSES together when a new year is published.
"""

from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")

# Full cash closes. Early-close sessions are not listed here.
HOLIDAYS: dict[date, str] = {
    # 2026
    date(2026, 1, 1): "New Year's Day",
    date(2026, 1, 19): "Martin Luther King, Jr. Day",
    date(2026, 2, 16): "Washington's Birthday",
    date(2026, 4, 3): "Good Friday",
    date(2026, 5, 25): "Memorial Day",
    date(2026, 6, 19): "Juneteenth",
    date(2026, 7, 3): "Independence Day observed",
    date(2026, 9, 7): "Labor Day",
    date(2026, 11, 26): "Thanksgiving Day",
    date(2026, 12, 25): "Christmas Day",
    # 2027
    date(2027, 1, 1): "New Year's Day",
    date(2027, 1, 18): "Martin Luther King, Jr. Day",
    date(2027, 2, 15): "Washington's Birthday",
    date(2027, 3, 26): "Good Friday",
    date(2027, 5, 31): "Memorial Day",
    date(2027, 6, 18): "Juneteenth observed",
    date(2027, 7, 5): "Independence Day observed",
    date(2027, 9, 6): "Labor Day",
    date(2027, 11, 25): "Thanksgiving Day",
    date(2027, 12, 24): "Christmas Day observed",
    # 2028 — included so July 3 early close is explicit. January 1 2028 is a
    # Saturday and is not an observed NYSE holiday.
    date(2028, 1, 17): "Martin Luther King, Jr. Day",
    date(2028, 2, 21): "Washington's Birthday",
    date(2028, 4, 14): "Good Friday",
    date(2028, 5, 29): "Memorial Day",
    date(2028, 6, 19): "Juneteenth",
    date(2028, 7, 4): "Independence Day",
    date(2028, 9, 4): "Labor Day",
    date(2028, 11, 23): "Thanksgiving Day",
    date(2028, 12, 25): "Christmas Day",
}

# Cash equity early closes, 13:00 ET. These remain trading days.
EARLY_CLOSES: dict[date, str] = {
    date(2026, 11, 27): "Day after Thanksgiving",
    date(2026, 12, 24): "Christmas Eve",
    date(2027, 11, 26): "Day after Thanksgiving",
    date(2028, 7, 3): "Day before Independence Day",
    date(2028, 11, 24): "Day after Thanksgiving",
}

REGULAR_CLOSE = "16:00"
EARLY_CLOSE = "13:00"


def is_weekend(day: date) -> bool:
    return day.weekday() >= 5


def holiday_name(day: date) -> str | None:
    return HOLIDAYS.get(day)


def is_trading_day(day: date) -> bool:
    return not is_weekend(day) and day not in HOLIDAYS


def is_early_close(day: date) -> bool:
    return day in EARLY_CLOSES


def close_hhmm(day: date) -> str:
    if day in EARLY_CLOSES:
        return EARLY_CLOSE
    return REGULAR_CLOSE


def close_time(day: date) -> time:
    hour, minute = close_hhmm(day).split(":")
    return time(int(hour), int(minute))


def previous_trading_day(day: date) -> date:
    cursor = date.fromordinal(day.toordinal() - 1)
    while not is_trading_day(cursor):
        cursor = date.fromordinal(cursor.toordinal() - 1)
    return cursor


def as_ny(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return moment.astimezone(NY)


def in_post_close_window(moment: datetime) -> bool:
    """True for 16:05–17:05 America/New_York.

    The two UTC crons are an hour apart (20:15 and 21:15). This window accepts
    the one that lands on 16:15 ET and a late runner, and rejects the other
    offset unless that run is delayed until after the cash close.
    """
    local = as_ny(moment)
    minutes = local.hour * 60 + local.minute
    return 16 * 60 + 5 <= minutes <= 17 * 60 + 5


def in_morning_window(moment: datetime) -> bool:
    """True for 07:50–08:45 America/New_York.

    08:00 ET is 12:00 UTC during EDT and 13:00 UTC during EST. The window stops
    before 09:00 so the off-offset cron does not also run.
    """
    local = as_ny(moment)
    minutes = local.hour * 60 + local.minute
    return 7 * 60 + 50 <= minutes <= 8 * 60 + 45
