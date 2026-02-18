# 📈 Crypto Signal Bot

A Telegram bot that monitors real-time futures trades on **MEXC** and **Binance**, and sends alerts when unusual price movements or high-volume "smart money" activity is detected.

---

## Features

- **Dual-exchange monitoring** — connects simultaneously to MEXC and Binance futures WebSocket feeds
- **Price spike alerts** — notifies when a symbol moves ≥3% between consecutive trades
- **Smart money detection** — alerts on breakouts (±0.2% beyond recent highs/lows) accompanied by volume spikes 7× above average
- **Per-chat exclusions** — each user can exclude specific symbols they don't want to receive alerts for
- **Auto-reconnect** — WebSocket connections restart automatically on failure

---

## Requirements

- Python 3.10+
- A Telegram bot token (from [@BotFather](https://t.me/BotFather))

Install dependencies:

```bash
pip install python-telegram-bot websockets requests python-dotenv
```

---

## Setup

1. Clone the repo and navigate into the project folder.
2. Create a `.env` file in the root directory:

```env
BOT_TOKEN=your_telegram_bot_token_here
```

3. Run the bot:

```bash
python bot.py
```

---

## Commands

| Command | Description |
|---|---|
| `/start` | Activate signals for your chat |
| `/stop` | Deactivate signals |
| `/exclude SYMBOL` | Exclude one or more symbols (e.g. `/exclude BTCUSDT ETHUSDT`) |

---

## How It Works

1. On startup, the bot fetches all active USDT-margined futures pairs from both MEXC and Binance.
2. It subscribes to trade streams for every pair via WebSocket.
3. Each incoming trade is checked against two conditions:
   - **Price change ≥ 3%** since the last seen price → signal sent
   - **Breakout + volume spike** (smart money pattern) → signal sent
4. Signals include a direct link to the trading pair on the respective exchange.
5. Volume data older than 3 minutes is automatically cleaned up.

---

## Notes

- The bot holds all state in memory — restarting it resets active chats, exclusions, and price history.
- For production use, consider persisting `active_chats` and `excluded_pairs` to a database.
- Running against a large number of pairs generates significant WebSocket traffic; ensure your server has adequate bandwidth.
