"""
Market calendar module.
Handles NSE holidays, weekends, market hours, and signal windows.
All times in IST.
"""

from datetime import datetime, date, time, timezone, timedelta

IST = timezone(timedelta(hours=5, minutes=30))

# NSE Trading Holidays (official circulars)
NSE_HOLIDAYS = {
    # 2025 holidays
    date(2025, 2, 26),   # Mahashivratri
    date(2025, 3, 14),   # Holi
    date(2025, 3, 31),   # Id-Ul-Fitr
    date(2025, 4, 10),   # Shri Mahavir Jayanti
    date(2025, 4, 14),   # Dr. Ambedkar Jayanti
    date(2025, 4, 18),   # Good Friday
    date(2025, 5, 1),    # Maharashtra Day
    date(2025, 8, 15),   # Independence Day
    date(2025, 8, 27),   # Ganesh Chaturthi
    date(2025, 10, 2),   # Mahatma Gandhi Jayanti / Dussehra
    date(2025, 10, 21),  # Diwali Laxmi Pujan
    date(2025, 10, 22),  # Diwali Balipratipada
    date(2025, 11, 5),   # Guru Nanak Jayanti
    date(2025, 12, 25),  # Christmas

    # 2026 holidays
    date(2026, 1, 26),   # Republic Day
    date(2026, 3, 3),    # Holi
    date(2026, 3, 26),   # Shri Ram Navami
    date(2026, 3, 31),   # Shri Mahavir Jayanti
    date(2026, 4, 3),    # Good Friday
    date(2026, 4, 14),   # Dr. Ambedkar Jayanti
    date(2026, 5, 1),    # Maharashtra Day
    date(2026, 5, 28),   # Bakri Id
    date(2026, 6, 26),   # Muharram
    date(2026, 9, 14),   # Ganesh Chaturthi
    date(2026, 10, 2),   # Mahatma Gandhi Jayanti
    date(2026, 10, 20),  # Dussehra
    date(2026, 11, 10),  # Diwali Balipratipada
    date(2026, 11, 24),  # Guru Nanak Jayanti
    date(2026, 12, 25),  # Christmas
}

# Market timing constants (IST)
MARKET_OPEN = time(9, 15)
MARKET_CLOSE = time(15, 30)
SIGNAL_WINDOW_START = time(9, 30)
SIGNAL_WINDOW_END = time(14, 30)
SQUARE_OFF_TIME = time(15, 15)


def get_ist_now() -> datetime:
    """Get current datetime in IST."""
    return datetime.now(IST)


def is_weekend(dt: date = None) -> bool:
    """Check if date is Saturday (5) or Sunday (6)."""
    if dt is None:
        dt = get_ist_now().date()
    return dt.weekday() in (5, 6)


def is_nse_holiday(dt: date = None) -> bool:
    """Check if date is an NSE holiday."""
    if dt is None:
        dt = get_ist_now().date()
    return dt in NSE_HOLIDAYS


def get_holiday_name(dt: date) -> str:
    """Get the name of the NSE holiday, if any."""
    holiday_names = {
        date(2025, 2, 26): "Mahashivratri",
        date(2025, 3, 14): "Holi",
        date(2025, 3, 31): "Id-Ul-Fitr",
        date(2025, 4, 10): "Shri Mahavir Jayanti",
        date(2025, 4, 14): "Dr. Ambedkar Jayanti",
        date(2025, 4, 18): "Good Friday",
        date(2025, 5, 1): "Maharashtra Day",
        date(2025, 8, 15): "Independence Day",
        date(2025, 8, 27): "Ganesh Chaturthi",
        date(2025, 10, 2): "Mahatma Gandhi Jayanti / Dussehra",
        date(2025, 10, 21): "Diwali Laxmi Pujan",
        date(2025, 10, 22): "Diwali Balipratipada",
        date(2025, 11, 5): "Guru Nanak Jayanti",
        date(2025, 12, 25): "Christmas",
        date(2026, 1, 26): "Republic Day",
        date(2026, 3, 3): "Holi",
        date(2026, 3, 26): "Shri Ram Navami",
        date(2026, 3, 31): "Shri Mahavir Jayanti",
        date(2026, 4, 3): "Good Friday",
        date(2026, 4, 14): "Dr. Ambedkar Jayanti",
        date(2026, 5, 1): "Maharashtra Day",
        date(2026, 5, 28): "Bakri Id",
        date(2026, 6, 26): "Muharram",
        date(2026, 9, 14): "Ganesh Chaturthi",
        date(2026, 10, 2): "Mahatma Gandhi Jayanti",
        date(2026, 10, 20): "Dussehra",
        date(2026, 11, 10): "Diwali Balipratipada",
        date(2026, 11, 24): "Guru Nanak Jayanti",
        date(2026, 12, 25): "Christmas",
    }
    return holiday_names.get(dt, "Unknown Holiday")


def is_trading_day(dt: date = None) -> bool:
    """Check if the given date is a valid trading day (not weekend, not holiday)."""
    if dt is None:
        dt = get_ist_now().date()
    return not is_weekend(dt) and not is_nse_holiday(dt)


def is_market_hours(dt: datetime = None) -> bool:
    """Check if current time is within market hours (9:15 AM - 3:30 PM IST)."""
    if dt is None:
        dt = get_ist_now()
    current_time = dt.time()
    return MARKET_OPEN <= current_time <= MARKET_CLOSE


def is_signal_window(dt: datetime = None) -> bool:
    """Check if current time is within signal generation window (9:30 AM - 2:30 PM IST)."""
    if dt is None:
        dt = get_ist_now()
    current_time = dt.time()
    return SIGNAL_WINDOW_START <= current_time <= SIGNAL_WINDOW_END


def is_square_off_time(dt: datetime = None) -> bool:
    """Check if it's time for auto square-off (3:15 PM IST)."""
    if dt is None:
        dt = get_ist_now()
    current_time = dt.time()
    # Trigger square-off between 3:15 PM and 3:16 PM
    return time(15, 15) <= current_time <= time(15, 16)


def should_bot_run(dt: datetime = None) -> tuple:
    """
    Check if the bot should be active right now.
    Returns (should_run: bool, reason: str)
    """
    if dt is None:
        dt = get_ist_now()

    today = dt.date()

    if is_weekend(today):
        day_name = "Saturday" if today.weekday() == 5 else "Sunday"
        return False, f"Market closed: {day_name} (weekend)"

    if is_nse_holiday(today):
        name = get_holiday_name(today)
        return False, f"Market closed: {name} (NSE holiday)"

    if not is_market_hours(dt):
        if dt.time() < MARKET_OPEN:
            return False, f"Before market hours (opens at {MARKET_OPEN.strftime('%H:%M')} IST)"
        else:
            return False, f"After market hours (closed at {MARKET_CLOSE.strftime('%H:%M')} IST)"

    return True, "Market is open"


def is_non_trading_day(dt: date = None) -> bool:
    """Check if the given date is a non-trading day."""
    return not is_trading_day(dt)
