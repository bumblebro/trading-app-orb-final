# Nifty 50 Trading Dashboard

A professional, full-stack automated trading dashboard for Nifty 50 Options (CE/PE) built with **Next.js 14**, **Python FastAPI**, and **Angel One SmartAPI**.

## 🚀 Features
- **Real-time Charting**: Interactive 5-min candlestick chart with EMA 9, EMA 21, and VWAP overlays.
- **Smart Bot Engine**: Automated signal generation using EMA Crossover + VWAP + RSI.
- **Security First**: Paper Trading mode by default with full simulation for safe testing.
- **Risk Management**: Auto square-off at 3:15 PM IST, NSE holiday guards, and trade circuit breakers.
- **Detailed History**: Full tracking of trades, P&L, win rates, and live logs.

---

## 🛠 Tech Stack
- **Frontend**: Next.js 14 (App Router), Tailwind CSS v4, Lightweight Charts (TradingView)
- **Backend**: Python FastAPI, Angel One SmartAPI
- **Real-time**: WebSocket (SmartWebSocketV2)
- **Database**: SQLite (for trades, settings, and logs)

---

## ⚙️ Setup & Installation

### 1. Backend (Python Bot)
Navigate to the `bot` directory:
```bash
cd bot
```
Create a virtual environment and install dependencies:
```bash
python3 -m venv venv
source venv/bin/activate  # On Mac/Linux
pip install -r requirements.txt
```

### 2. Frontend (Next.js)
Navigate back to the root directory and install dependencies:
```bash
npm install
```

---

## 🏃 Operation Guide

### Step 1: Start the Trading Bot Server
```bash
cd bot
python server.py
```
*The bot server will start on `http://localhost:8000`*

### Step 2: Start the Dashboard
```bash
npm run dev
```
*Open [http://localhost:3000](http://localhost:3000) in your browser.*

---

## 🧪 Testing the Dashboard (Paper Trading)

You can test the entire flow in **Simulation Mode** without using real money or Angel One credentials.

1. **Bot Start**: Click the **"▶ Start Bot"** button on the dashboard.
2. **Monitor Logs**: Check the bottom logs for `Bot STARTED` and `WebSocket CONNECTED`.
3. **Price Feed**: You should see the Nifty 50 price and chart updating every second using simulated data.
4. **Active Trade**: If a signal (EMA Crossover) is generated, a trade will appear on the **Active Trade** page.
5. **Exit Trade**: Go to the **Active Trade** page and use the **Manual Exit** button to close a position and see the P&L update.
6. **Verify History**: Check the **History** page to see your closed paper trades.

---

## 🔴 Live Trading Setup

To use real market data and place live orders:
1. Go to the **Settings** page in the dashboard.
2. Enter your **Angel One API Key, Client ID, Password, and TOTP Secret**.
3. Toggle the **Trading Mode** to "Live".
4. Type `CONFIRM` in the warning dialog to enable live trading.

---

## ⚖️ Liability Disclaimer
*This software is for educational purposes only. Trading options involves significant risk. The authors are not responsible for any financial losses incurred through the use of this software.*
