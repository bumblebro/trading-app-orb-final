# NIFTY Opening Range Breakout Bot

An automated intraday **Opening Range Breakout (ORB)** system for NIFTY 50 weekly
options, with a Next.js dashboard, a FastAPI bot server, and a research
backtester that runs the *same* strategy code as live trading.

> **Educational software.** Options trading can lose money faster than you expect.
> Nothing here is financial advice. Paper trade for months before risking capital.

---

## The strategy

Everything is decided by the first hour of the session.

| Step | Rule |
| --- | --- |
| 09:15 – 10:15 | Build the opening range: the high and low of the first 60 minutes. |
| Range check | Skip the day if the range is narrower than 0.25% or wider than 2.00% of spot. |
| Entry | A 3-minute candle must **close** more than 5% of the range width beyond the high (buy CE) or low (buy PE). No entries after 13:30. |
| Stop | The opposite side of the opening range. |
| Target | 2R. The stop moves to breakeven once the trade is 1R in profit. |
| Square off | 15:15, unconditionally. |
| Limit | One trade per day. |

The bot buys ATM weekly options rather than trading the index, so the index-level
stop and target are translated into option orders.

### Why these numbers

They came out of a parameter sweep over 2019–2026 NIFTY 1-minute data, chosen for
**agreement between in-sample and out-of-sample results** rather than peak
in-sample return. Three findings drove the defaults:

- **60 minutes beats the textbook 15.** A 15-minute range is roughly break-even
  after costs (PF ≈ 1.02); 60 minutes is comfortably profitable in both halves of
  the sample.
- **Wide breakout buffers are a trap.** A 0.30 buffer looked best in-sample
  (PF 1.49) and was the worst out-of-sample (PF 1.15). A 0.05 buffer is the most
  consistent across both.
- **The premium stop only destroyed value.** Every setting tighter than "off"
  reduced returns *without* reducing drawdown, because the index stop already
  bounds the loss. It defaults to off (100%) and stays configurable.

### Backtest results

1 lot (75 qty), 2019-01-01 → 2026-04-08, costs modelled at 1% slippage per side
plus real Indian brokerage, STT, exchange, SEBI, stamp and GST charges.

| | Trades | Net P&L | Win rate | Profit factor | Sharpe | Max DD |
| --- | --- | --- | --- | --- | --- | --- |
| In-sample (2019–2023) | 957 | ₹234,258 | 42.6% | 1.267 | — | ₹-33,202 |
| Out-of-sample (2024–2026) | 417 | ₹217,924 | 43.2% | 1.451 | — | ₹-29,394 |
| **All** | **1,374** | **₹452,182** | **42.8%** | **1.332** | **1.59** | **₹-33,202** |

Every one of the eight years is profitable, and out-of-sample performance is
*better* than in-sample — the opposite of the usual overfitting signature.

**Read this before trusting the numbers.** The CSV contains index prices only, so
option premiums are modelled with Black-Scholes using realised volatility, not
real option quotes. The edge is real but not enormous: it survives 1% slippage
per side (PF 1.31) and 2% (PF 1.14), and disappears entirely near 3%. Most trades
(74%) exit at the 15:15 square-off rather than at the target, so this is closer to
"ride the breakout until the close" than a target-driven system.

---

## Architecture

```
app/                    Next.js 16 dashboard (App Router)
  api/bot/[...path]/    single proxy to the Python server; injects the API token
components/             Navbar, Chart (lightweight-charts)
lib/                    typed API client and shared types
bot/
  strategy_orb.py       pure ORB state machine — no I/O, no globals
  trading_bot.py        session loop, day rollover, kill switch, order plumbing
  order_manager.py      paper + live execution, order slicing, fill verification
  data_feed.py          Angel One websocket, or CSV playback
  option_pricing.py     Black-Scholes ATM pricing and expiry calendar
  charges.py            Indian transaction cost model
  database.py           SQLite schema, migrations, settings
  server.py             FastAPI endpoints
  research/backtest.py  backtester and parameter sweeps
  tests/                52 tests over the strategy, pricing and charges
```

`strategy_orb.py` is deliberately pure and is imported by both the backtester and
the live bot, so simulated and live behaviour cannot drift apart.

---

## Setup

### Backend

```bash
cd bot
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Frontend

```bash
npm install
```

### Environment

Create `.env.local` in the project root:

```bash
PYTHON_BOT_URL=http://localhost:8000
BOT_API_TOKEN=<a long random string>
```

Export the same token for the bot server. `BOT_API_TOKEN` protects every
state-changing endpoint, and **live trading refuses to start without it**.

```bash
export BOT_API_TOKEN=<the same string>
export BOT_CORS_ORIGINS=http://localhost:3000
```

---

## Running

```bash
# terminal 1
cd bot && source venv/bin/activate && python server.py

# terminal 2
npm run dev
```

Open http://localhost:3000.

### Paper trading and playback

The defaults are paper mode with CSV playback, so you can exercise the whole
system with no broker account. Set the data source to *CSV playback* in Settings,
press **Start bot**, and the dashboard will replay `bot/data/nifty_sample.csv`
through the live code path.

### Going live

#### Get Angel One credentials

You need an Angel One demat/trading account, then a SmartAPI app and TOTP.

1. **Trading account** — open or activate one at [angelone.in](https://www.angelone.in).
   Note your **Client ID** (client code) and trading **PIN**.

2. **API key** — go to [smartapi.angelone.in](https://smartapi.angelone.in), sign up /
   log in with the same account, and **Create an App**:
   - API type: **Trading API**
   - Redirect URL: `https://localhost` or `http://127.0.0.1` is fine locally
   - Copy the **API Key** after the app is created

3. **TOTP secret** — open
   [Enable TOTP](https://smartapi.angelbroking.com/enable-totp), enter Client ID +
   PIN, verify the OTP from email/SMS, then copy the **secret string** shown with
   the QR code (long base32 text). Optionally scan the QR into Google Authenticator
   as well.

   Paste that **secret string** into Settings — not the rotating 6-digit code. The
   bot generates the code with `pyotp`.

| Angel One | Settings field |
| --- | --- |
| API Key from SmartAPI app | API key |
| Client code | Client ID |
| Trading PIN | PIN |
| TOTP secret string | TOTP secret |

Do not share these values. They are stored server-side and masked in the UI.

#### Start live trading

1. In Settings, fill in the four broker fields above.
2. Set **Price source** to **Angel One live feed** (`smartapi`). Playback skips
   broker login and will not place live orders correctly.
3. Set **Trading mode** to **Live**.
4. Restart the bot with `BOT_API_TOKEN` exported (same value as `.env.local`), or
   live start is refused.
5. Press **Start bot** on the dashboard.

---

## Research

```bash
cd bot

# single run on the current defaults
python research/backtest.py --run

# parameter sweeps: structure | filters | exits | risk | quick | full
python research/backtest.py --sweep filters --workers 7 --out /tmp/filters.json

# override any OrbConfig field
python research/backtest.py --run --config '{"or_minutes":30,"target_r":3.0}'
```

Sweeps report in-sample and out-of-sample metrics side by side and rank by
in-sample only, so out-of-sample stays an honest check rather than another knob.

## Tests

```bash
python -m pytest bot/tests -q
```

---

## Operational notes

- **Kill switch.** Hitting `max_daily_loss` flattens any open position and stops
  trading for the rest of the day.
- **Order execution.** Live entries are sliced to respect exchange freeze limits,
  retried, and verified against the order book. If a slice fails mid-entry, the
  filled portion is unwound rather than left as an unintended position.
- **Secrets.** `GET /settings` masks credentials; saving a masked value is treated
  as "unchanged" so the real secret is never overwritten by the UI.
- **Charges** are shared between the backtester and the live bot, so reported P&L
  is comparable across both.

## Deployment

```bash
git add . && git commit -m "..." && git push origin main

ssh root@your_droplet_ip
cd ~/trading-app-orb-final
git checkout -- bot/trading.db && git pull origin main

cd bot
docker stop nifty-bot && docker rm nifty-bot
docker build -t trading-bot .
docker run -d --name nifty-bot -p 8000:8000 \
  -e BOT_API_TOKEN="$BOT_API_TOKEN" \
  -e BOT_CORS_ORIGINS="https://your-dashboard-domain" \
  -v $(pwd)/trading.db:/app/trading.db \
  --restart always trading-bot
```
