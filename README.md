# NIFTY Opening Range Breakout Bot

Intraday **Opening Range Breakout (ORB)** system for NIFTY 50 weekly options —
Next.js dashboard, FastAPI bot, and a research backtester that shares the same
strategy code as live trading.

> **Educational software.** Options can lose money quickly. Not financial advice.
> Paper trade before risking capital.

---

## Strategy

| Step | Rule |
| --- | --- |
| 09:15 – 10:15 | Build opening range (high/low of first 60 minutes) |
| Range check | Skip if range &lt; 0.25% or &gt; 2.00% of spot |
| Entry | 3-min candle **closes** beyond high/low by 5% of range width (CE/PE). No entries after 13:30 |
| Stop | Opposite side of the opening range |
| Target | 2R; stop → breakeven after 1R |
| Square off | 15:15 always |
| Limit | One trade per day |

Buys ATM weekly options. Defaults came from a 2019–2026 parameter sweep chosen
for in-sample / out-of-sample agreement (not peak in-sample return). Typical win
rate ~43%; most exits are square-off. Premiums in research are Black-Scholes
modelled from index data, not live option quotes.

---

## Setup (local / Mac)

```bash
# backend
cd bot
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# frontend (repo root)
npm install
```

Create `.env.local` in the project root:

```bash
PYTHON_BOT_URL=http://localhost:8000
BOT_API_TOKEN=<a long random string>
```

Same token must be set for the bot process (live trading requires it):

```bash
export BOT_API_TOKEN=<the same string>
export BOT_CORS_ORIGINS=http://localhost:3000
```

### Run locally

```bash
# terminal 1 — bot
cd bot && source venv/bin/activate
export BOT_API_TOKEN=<the same string>
python server.py

# terminal 2 — UI
npm run dev
```

Open http://localhost:3000.

- **Paper / playback:** Settings → data source *CSV playback* → Start bot.
- **Live:** Angel credentials + *Angel One live feed* + *Live* mode → Start bot.
  Keep the Mac awake during market hours.

Credentials are saved in the bot DB (enter once). Angel session is created on
each bot start; if the feed dies, restart the bot.

---

## Angel One credentials

1. Trading account at [angelone.in](https://www.angelone.in) — note **Client ID** and **PIN**.
2. [smartapi.angelone.in](https://smartapi.angelone.in) → Create App → **Trading API** → copy **API Key**.
3. [Enable TOTP](https://smartapi.angelbroking.com/enable-totp) → copy the **secret string** (not the 6-digit code).

| Angel One | Settings field |
| --- | --- |
| API Key | API key |
| Client code | Client ID |
| Trading PIN | PIN |
| TOTP secret string | TOTP secret |

---

## Capital & sizing phases

**Phase 0 — Plumbing (2–4 weeks):** ₹15k–25k, fixed 1 lot, max 1 lot. Test fills/stops.

**Phase 1 — Prove live (1–3 months):** ₹25k–50k, still fixed 1 lot.

**Phase 2 — Scale:** ₹75k–1.5L, fixed 2 lots only if Phase 1 is fine.

**Phase 3 — Risk %:** Only after months of stable live data. Risk 0.5–1%, max lots 3–5,
max capital per trade 10–15%.

```text
New / unsure     → Fixed 1 lot
Stable live      → Fixed 2 lots
Proven + bigger  → Risk 0.5–1% + max-lots cap
```

---

## Deploy bot on DigitalOcean

Run the **bot** on a Droplet. Keep the **UI** on your Mac (or Vercel later).

**Droplet:** Ubuntu, **$6 / 1 GB RAM** (not 512 MB). Region: **Bangalore**, else **Singapore**.  
**Current IP:** `168.144.177.107` (SSH: `ssh root@168.144.177.107`).

### On the droplet (SSH first — not on your Mac)

```bash
ssh root@168.144.177.107

apt update && apt install -y git python3 python3-venv python3-pip
cd ~
git clone https://github.com/bumblebro/trading-app-orb-final.git
cd trading-app-orb-final/bot
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Env file

```bash
cat >/etc/nifty-orb.env <<EOF
BOT_API_TOKEN=<same token as .env.local>
BOT_CORS_ORIGINS=http://localhost:3000
EOF
chmod 600 /etc/nifty-orb.env
```

### systemd service

```bash
cat >/etc/systemd/system/nifty-orb.service <<'EOF'
[Unit]
Description=NIFTY ORB bot API
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/trading-app-orb-final/bot
EnvironmentFile=/etc/nifty-orb.env
ExecStart=/root/trading-app-orb-final/bot/venv/bin/python server.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now nifty-orb
ufw allow OpenSSH
ufw allow 8000/tcp
ufw --force enable
```

Point `.env.local` at the droplet:

```bash
PYTHON_BOT_URL=http://168.144.177.107:8000
BOT_API_TOKEN=<same token>
```

### Restart / logs

```bash
ssh root@168.144.177.107

systemctl restart nifty-orb
systemctl status nifty-orb
journalctl -u nifty-orb -f
```

### How to push server changes to droplet (for next time)

Do this whenever bot code on your Mac needs to land on the droplet.

**1. On your Mac** — commit (if needed) and push:

```bash
cd ~/Documents/trading-app-orb-final
git add -A
git status   # confirm you are not committing .env.local or secrets
git commit -m "describe the change"
git push origin main
```

**2. On your Mac** — one command to update the droplet (after step 1 is on GitHub):

```bash
ssh root@168.144.177.107 'cd ~/trading-app-orb-final && cp bot/trading.db ~/trading.db.bak && git checkout -- bot/trading.db bot/trading.log bot/instruments_cache.json && git pull origin main && cp ~/trading.db.bak bot/trading.db && systemctl restart nifty-orb && systemctl status nifty-orb --no-pager'
```

That keeps `trading.db`, discards runtime noise that blocks pull (`trading.log`, `instruments_cache.json`), pulls `main`, restores the DB, restarts the bot.

For **WebSocket / feed** fixes, prefer a longer gap instead of plain restart:

```bash
ssh root@168.144.177.107 'cd ~/trading-app-orb-final && cp bot/trading.db ~/trading.db.bak && git checkout -- bot/trading.db bot/trading.log bot/instruments_cache.json && git pull origin main && cp ~/trading.db.bak bot/trading.db && systemctl stop nifty-orb && sleep 120 && systemctl start nifty-orb && systemctl status nifty-orb --no-pager'
```

**3. In the UI** (Mac / localhost): Stop bot if it still shows running, then Start bot once. Check logs for `WebSocket CONNECTED` when using the live Angel feed.

If `git pull` still complains about another local file, add it to the `git checkout -- ...` list — never wipe `trading.db` without a backup.

### If the bot freezes with an open trade

1. Dashboard **Exit now**, or  
2. `systemctl restart nifty-orb` — it reloads the open trade from the DB, or  
3. Square off manually in the Angel One app (backup).

---

## Research & tests

```bash
cd bot
python research/backtest.py --run
python research/backtest.py --sweep filters --workers 7 --out /tmp/filters.json
python -m pytest tests -q
```

---

## Notes

- **Kill switch:** `max_daily_loss` flattens and stops trading for the day.
- **Live orders:** sliced for NSE freeze limits; partial entry failures are unwound.
- **Clear history:** Trades page → Clear history (or Settings). Does not delete credentials.
