"""
Transaction cost model for NIFTY option trades on a discount broker.

Kept dependency-free so both the live bot and the research backtester charge
trades identically.
"""

from typing import Dict

BROKERAGE_PER_ORDER = 20.0
STT_SELL_RATE = 0.0005          # 0.05% on the sell-side premium
EXCHANGE_TXN_RATE = 0.00053     # NFO turnover
SEBI_RATE = 0.0000001           # Rs 10 per crore
STAMP_DUTY_BUY_RATE = 0.00003   # 0.003% on the buy side
GST_RATE = 0.18


def calculate_charges(entry_price: float, exit_price: float, quantity: int) -> Dict[str, float]:
    """Round-trip costs for a buy-then-sell option trade."""
    buy_value = entry_price * quantity
    sell_value = exit_price * quantity
    turnover = buy_value + sell_value

    brokerage = BROKERAGE_PER_ORDER * 2  # entry + exit
    stt = round(sell_value * STT_SELL_RATE, 2)
    exc_charges = round(turnover * EXCHANGE_TXN_RATE, 2)
    sebi = round(turnover * SEBI_RATE, 2)
    stamp = round(buy_value * STAMP_DUTY_BUY_RATE, 2)
    gst = round((brokerage + exc_charges + sebi) * GST_RATE, 2)

    total = round(brokerage + stt + exc_charges + sebi + stamp + gst, 2)
    return {
        "brokerage": brokerage,
        "stt": stt,
        "exc_charges": exc_charges,
        "gst": gst,
        "total_charges": total,
    }
