"""
NFO Instrument Manager.
Downloads Angel One instrument master, filters for NIFTY options,
and provides strike/token lookup with expiry handling.
"""

import os
import json
import requests
from datetime import datetime, date, timedelta, timezone
from typing import Optional, List, Dict
from market_calendar import NSE_HOLIDAYS, is_nse_holiday

IST = timezone(timedelta(hours=5, minutes=30))

INSTRUMENT_MASTER_URL = "https://margincalculator.angelone.in/OpenAPI_File/files/OpenAPIScripMaster.json"
CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "instruments_cache.json")
NIFTY_STRIKE_INTERVAL = 50
DEFAULT_LOT_SIZE = 65


class InstrumentManager:
    """Manages NFO instrument data for NIFTY options."""

    def __init__(self):
        self.instruments: List[Dict] = []
        self.nifty_options: List[Dict] = []
        self._lot_size: int = DEFAULT_LOT_SIZE
        self._last_loaded: Optional[date] = None

    def load_instruments(self, force: bool = False):
        """
        Load instrument master data.
        Downloads fresh data once per trading day, uses cache otherwise.
        """
        today = datetime.now(IST).date()

        # Check if already loaded today
        if not force and self._last_loaded == today and self.nifty_options:
            return

        # Try loading from cache first
        if not force and self._load_from_cache(today):
            self._filter_nifty_options()
            self._last_loaded = today
            return

        # Download fresh data
        try:
            print(f"[InstrumentManager] Downloading instrument master...")
            response = requests.get(INSTRUMENT_MASTER_URL, timeout=60)
            response.raise_for_status()
            self.instruments = response.json()

            # Save to cache
            self._save_to_cache(today)
            self._filter_nifty_options()
            self._last_loaded = today
            print(f"[InstrumentManager] Loaded {len(self.instruments)} instruments, "
                  f"{len(self.nifty_options)} NIFTY options")
        except Exception as e:
            print(f"[InstrumentManager] Failed to download: {e}")
            # Try cache even if stale
            if self._load_from_cache():
                self._filter_nifty_options()

    def _load_from_cache(self, today: date = None) -> bool:
        """Load instruments from local cache file."""
        try:
            if not os.path.exists(CACHE_FILE):
                return False

            with open(CACHE_FILE, "r") as f:
                cache_data = json.load(f)

            cache_date = cache_data.get("date")
            if today and cache_date != str(today):
                return False

            self.instruments = cache_data.get("instruments", [])
            return len(self.instruments) > 0
        except Exception:
            return False

    def _save_to_cache(self, today: date):
        """Save instruments to local cache file."""
        try:
            cache_data = {
                "date": str(today),
                "instruments": self.instruments
            }
            with open(CACHE_FILE, "w") as f:
                json.dump(cache_data, f)
        except Exception as e:
            print(f"[InstrumentManager] Cache save failed: {e}")

    def _filter_nifty_options(self):
        """Filter for NIFTY index options from instrument list."""
        self.nifty_options = [
            inst for inst in self.instruments
            if (inst.get("exch_seg") == "NFO" and
                inst.get("name") == "NIFTY" and
                inst.get("instrumenttype") == "OPTIDX")
        ]

        # Extract lot size from instrument data
        if self.nifty_options:
            lot_str = self.nifty_options[0].get("lotsize", str(DEFAULT_LOT_SIZE))
            try:
                self._lot_size = int(lot_str)
            except (ValueError, TypeError):
                self._lot_size = DEFAULT_LOT_SIZE

    def get_lot_size(self) -> int:
        """
        Get current NIFTY lot size from instrument master.
        Falls back to DEFAULT_LOT_SIZE (65) if not available.
        """
        if not self.nifty_options:
            self.load_instruments()
        return self._lot_size

    def get_atm_strike(self, nifty_price: float) -> int:
        """
        Get At The Money strike price.
        Rounds to nearest NIFTY strike interval (50).
        """
        return round(nifty_price / NIFTY_STRIKE_INTERVAL) * NIFTY_STRIKE_INTERVAL

    def get_nearest_expiry(self, from_date: date = None) -> Optional[date]:
        """
        Find the nearest weekly expiry date.
        Weekly expiry = every Thursday.
        If Thursday is an NSE holiday → shifts to Wednesday.
        If Wednesday is also a holiday → shifts to Tuesday (walk backwards).
        """
        if from_date is None:
            from_date = datetime.now(IST).date()

        # Find the next Thursday (weekday 3)
        days_until_thursday = (3 - from_date.weekday()) % 7
        if days_until_thursday == 0 and from_date.weekday() == 3:
            # Today is Thursday — check if market is still open
            now = datetime.now(IST)
            if now.hour >= 15 and now.minute >= 30:
                days_until_thursday = 7  # Move to next Thursday
        next_thursday = from_date + timedelta(days=days_until_thursday)

        # If next_thursday is in the past or today after market close, get next week's
        if next_thursday < from_date:
            next_thursday += timedelta(days=7)

        # Apply holiday shift: walk backward from Thursday if it's a holiday
        expiry = next_thursday
        for _ in range(5):  # Max 5 days back (shouldn't need more)
            if not is_nse_holiday(expiry) and expiry.weekday() < 5:  # Not holiday, not weekend
                return expiry
            expiry -= timedelta(days=1)

        # Fallback: return original Thursday
        return next_thursday

    def get_option_token(self, strike: int, option_type: str,
                         expiry: date = None) -> Optional[str]:
        """
        Get the instrument token for a specific NIFTY option contract.
        option_type: 'CE' or 'PE'
        """
        if not self.nifty_options:
            self.load_instruments()

        if expiry is None:
            expiry = self.get_nearest_expiry()

        if expiry is None:
            return None

        expiry_str = expiry.strftime("%d%b%Y").upper()  # e.g., "17APR2026"

        for inst in self.nifty_options:
            inst_strike = inst.get("strike", "")
            inst_symbol = inst.get("symbol", "")
            inst_expiry = inst.get("expiry", "")

            try:
                inst_strike_val = float(inst_strike) / 100  # Strike is stored as strike*100
            except (ValueError, TypeError):
                continue

            if (int(inst_strike_val) == strike and
                inst_symbol.endswith(option_type) and
                inst_expiry.upper() == expiry_str):
                return inst.get("token")

        return None

    def get_trading_symbol(self, strike: int, option_type: str,
                           expiry: date = None) -> Optional[str]:
        """
        Get the full trading symbol for a NIFTY option.
        e.g., 'NIFTY17APR2622500CE'
        """
        if not self.nifty_options:
            self.load_instruments()

        if expiry is None:
            expiry = self.get_nearest_expiry()

        if expiry is None:
            return None

        expiry_str = expiry.strftime("%d%b%Y").upper()

        for inst in self.nifty_options:
            inst_strike = inst.get("strike", "")
            inst_symbol = inst.get("symbol", "")
            inst_expiry = inst.get("expiry", "")

            try:
                inst_strike_val = float(inst_strike) / 100
            except (ValueError, TypeError):
                continue

            if (int(inst_strike_val) == strike and
                inst_symbol.endswith(option_type) and
                inst_expiry.upper() == expiry_str):
                return inst_symbol

        # Construct manually if not found
        return f"NIFTY{expiry.strftime('%d%b%Y').upper()}{strike}{option_type}"

    def get_option_info(self, strike: int, option_type: str,
                        expiry: date = None) -> Optional[Dict]:
        """
        Get complete instrument info for a NIFTY option.
        Returns token, symbol, lot size, etc.
        """
        if not self.nifty_options:
            self.load_instruments()

        token = self.get_option_token(strike, option_type, expiry)
        symbol = self.get_trading_symbol(strike, option_type, expiry)

        if token:
            return {
                "token": token,
                "symbol": symbol,
                "strike": strike,
                "option_type": option_type,
                "expiry": str(expiry) if expiry else str(self.get_nearest_expiry()),
                "lot_size": self.get_lot_size(),
                "exchange": "NFO"
            }
        return None

    def get_available_strikes(self, expiry: date = None,
                              around_price: float = None,
                              range_points: int = 500) -> List[Dict]:
        """
        Get available strikes for a given expiry.
        Optionally filter around a price within range_points.
        """
        if not self.nifty_options:
            self.load_instruments()

        if expiry is None:
            expiry = self.get_nearest_expiry()

        expiry_str = expiry.strftime("%d%b%Y").upper() if expiry else ""
        strikes = []

        for inst in self.nifty_options:
            if inst.get("expiry", "").upper() == expiry_str:
                try:
                    strike_val = float(inst.get("strike", "0")) / 100
                except (ValueError, TypeError):
                    continue

                if around_price:
                    if abs(strike_val - around_price) > range_points:
                        continue

                strikes.append({
                    "strike": int(strike_val),
                    "token": inst.get("token"),
                    "symbol": inst.get("symbol"),
                    "type": "CE" if inst.get("symbol", "").endswith("CE") else "PE"
                })

        return sorted(strikes, key=lambda x: (x["strike"], x["type"]))


# Global instance
_manager = None

def get_instrument_manager() -> InstrumentManager:
    """Get or create the global InstrumentManager instance."""
    global _manager
    if _manager is None:
        _manager = InstrumentManager()
    return _manager
