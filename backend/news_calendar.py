"""
Major Forex News Calendar for EURUSD backtesting.
Simulates spread/slippage spikes during high-impact events:
NFP, FOMC, ECB, US CPI.
"""
import calendar
from datetime import datetime, timezone, timedelta
from typing import Set


def _first_friday(year: int, month: int) -> int:
    cal = calendar.monthcalendar(year, month)
    for week in cal:
        if week[4] != 0:
            return week[4]
    return 7


def _generate_nfp_dates(start_year: int, end_year: int):
    dates = []
    for year in range(start_year, end_year + 1):
        for month in range(1, 13):
            day = _first_friday(year, month)
            dates.append(datetime(year, month, day, 13, 30, tzinfo=timezone.utc))
    return dates


FOMC_DATES = [
    "2024-01-31", "2024-03-20", "2024-05-01", "2024-06-12",
    "2024-07-31", "2024-09-18", "2024-11-07", "2024-12-18",
    "2025-01-29", "2025-03-19", "2025-05-07", "2025-06-18",
    "2025-07-30", "2025-09-17", "2025-11-05", "2025-12-17",
    "2026-01-28", "2026-03-18", "2026-05-06", "2026-06-17",
    "2026-07-29", "2026-09-16", "2026-11-04", "2026-12-16",
]

ECB_DATES = [
    "2024-01-25", "2024-03-07", "2024-04-11", "2024-06-06",
    "2024-07-18", "2024-09-12", "2024-10-17", "2024-12-12",
    "2025-01-30", "2025-03-06", "2025-04-17", "2025-06-05",
    "2025-07-24", "2025-09-11", "2025-10-30", "2025-12-18",
    "2026-01-22", "2026-03-05", "2026-04-16", "2026-06-04",
    "2026-07-16", "2026-09-10", "2026-10-29", "2026-12-10",
]


class NewsCalendar:
    def __init__(self):
        self.news_times: Set[str] = set()
        self._build()

    def _build(self):
        for dt in _generate_nfp_dates(2024, 2026):
            self._add(dt)
        for ds in FOMC_DATES:
            dt = datetime.strptime(ds, "%Y-%m-%d").replace(hour=19, minute=0, tzinfo=timezone.utc)
            self._add(dt)
        for ds in ECB_DATES:
            dt = datetime.strptime(ds, "%Y-%m-%d").replace(hour=13, minute=15, tzinfo=timezone.utc)
            self._add(dt)
        for year in range(2024, 2027):
            for month in range(1, 13):
                self._add(datetime(year, month, 12, 13, 30, tzinfo=timezone.utc))

    def _add(self, dt: datetime):
        self.news_times.add(dt.strftime("%Y-%m-%d %H:%M"))

    def is_news_window(self, dt: datetime, window_minutes: int = 3) -> bool:
        for offset in range(-window_minutes, window_minutes + 1):
            key = (dt + timedelta(minutes=offset)).strftime("%Y-%m-%d %H:%M")
            if key in self.news_times:
                return True
        return False


news_calendar = NewsCalendar()
