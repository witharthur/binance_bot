import asyncio
import time
import json
import requests
import os
from dotenv import load_dotenv
from collections import defaultdict, deque
from websockets import connect
from telegram import Bot, Update, BotCommand
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

# -----------------------------
# Load .env
# -----------------------------
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

# -----------------------------
# Config
# -----------------------------
MEXC_WS_URL = "wss://contract.mexc.com/edge"
MEXC_API_URL = "https://contract.mexc.com/api/v1/contract/detail"
BINANCE_WS_BASE = "wss://fstream.binance.com/stream?streams="

# -----------------------------
# GLOBAL DATA
# -----------------------------
volume_data = defaultdict(list)
price_data = {}
price_history = defaultdict(lambda: deque(maxlen=100))
lock = asyncio.Lock()
active_chats = set()
excluded_pairs = defaultdict(set)

# -----------------------------
# FORMAT SIGNAL
# -----------------------------
def format_signal(symbol: str, exchange: str) -> str:
    url = f"https://futures.mexc.com/ru-RU/exchange/{symbol}" if exchange == "MEXC" else f"https://www.binance.com/en/futures/{symbol}"
    return f"{symbol} ({exchange}) {url}"

# -----------------------------
# SEND SIGNAL
# -----------------------------
async def send_signal(chat_id, symbol, exchange):
    text = format_signal(symbol, exchange)
    try:
        await application.bot.send_message(
            chat_id=chat_id,
            text=text,
            disable_web_page_preview=True
        )
    except Exception as e:
        print(f"Send error: {e}")

# -----------------------------
# SMART MONEY DETECTION
# -----------------------------
async def check_smart_money(symbol, price, volume, exchange):
    prices = price_history[symbol]
    if len(prices) < 10:
        return

    highs = max(prices)
    lows = min(prices)
    breakout = price > highs * 1.002 or price < lows * 0.998

    if not breakout:
        return

    avg_volume = sum(v for v, _ in volume_data[symbol]) / max(len(volume_data[symbol]), 1)

    if volume < avg_volume * 7:
        return

    for chat_id in active_chats:
        if symbol in excluded_pairs[chat_id]:
            continue
        await send_signal(chat_id, symbol, exchange)

# -----------------------------
# PROCESS MESSAGE
# -----------------------------
async def process_message(symbol, price, volume, exchange):
    try:
        async with lock:
            price_history[symbol].append(price)
            volume_data[symbol].append((volume, int(time.time() * 1000)))

            if symbol in price_data:
                last_price = price_data[symbol]
                change = (price - last_price) / last_price * 100

                if abs(change) >= 3:
                    for chat_id in active_chats:
                        if symbol not in excluded_pairs[chat_id]:
                            await send_signal(chat_id, symbol, exchange)

            price_data[symbol] = price

        await check_smart_money(symbol, price, volume, exchange)
        await cleanup_old_data()
    except Exception as e:
        print(f"process_message error: {e}")

# -----------------------------
# CLEANUP OLD DATA
# -----------------------------
async def cleanup_old_data():
    t = int(time.time() * 1000) - 180000
    async with lock:
        for pair in list(volume_data.keys()):
            volume_data[pair] = [(v, ts) for v, ts in volume_data[pair] if ts > t]

# -----------------------------
# MEXC WEBSOCKET
# -----------------------------
async def mexc_ws():
    while True:
        try:
            print("Connecting to MEXC WebSocket...")
            async with connect(MEXC_WS_URL) as ws:
                cryptos = requests.get(MEXC_API_URL).json()["data"]
                usdt_pairs = [c["symbol"] for c in cryptos if c["symbol"].endswith("_USDT")]
                print("MEXC subscribed:", len(usdt_pairs))

                for symbol in usdt_pairs:
                    await ws.send(json.dumps({"method": "sub.deal", "param": {"symbol": symbol}}))

                while True:
                    msg = json.loads(await ws.recv())
                    if msg.get("channel") != "push.deal":
                        continue
                    trades = msg.get("data")
                    if isinstance(trades, list):
                        for trade in trades:
                            s = trade.get("s", msg.get("symbol"))
                            if s:
                                await process_message(s, float(trade["p"]), float(trade["v"]), "MEXC")

        except Exception as e:
            print("MEXC WS error:", e)
            await asyncio.sleep(3)

# -----------------------------
# BINANCE WEBSOCKET
# -----------------------------
async def binance_ws():
    while True:
        try:
            # Get USDT futures pairs
            r = requests.get("https://fapi.binance.com/fapi/v1/exchangeInfo").json()
            usdt_pairs = [s["symbol"].lower() for s in r["symbols"] if s["quoteAsset"] == "USDT" and s["status"] == "TRADING"]
            streams = "/".join([f"{s}@trade" for s in usdt_pairs])
            ws_url = BINANCE_WS_BASE + streams
            print("Connecting to Binance WebSocket...")
            async with connect(ws_url) as ws:
                print("Binance subscribed:", len(usdt_pairs))
                while True:
                    msg = json.loads(await ws.recv())
                    data = msg.get("data")
                    if data:
                        symbol = data["s"]
                        price = float(data["p"])
                        volume = float(data["q"])
                        await process_message(symbol, price, volume, "Binance")
        except Exception as e:
            print("Binance WS error:", e)
            await asyncio.sleep(3)

# -----------------------------
# COMMANDS
# -----------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    active_chats.add(chat_id)
    await update.message.reply_text("Бот активирован. Сигналы будут приходить.")

async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id in active_chats:
        active_chats.remove(chat_id)
    await update.message.reply_text("Бот остановлен. Сигналы не будут приходить.")

async def exclude(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not context.args:
        await update.message.reply_text("Использование: /exclude SYMBOL")
        return
    for symbol in context.args:
        excluded_pairs[chat_id].add(symbol.upper())
    await update.message.reply_text(f"{', '.join(context.args).upper()} исключены из сигналов.")

async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Доступные команды: /start, /stop")

# -----------------------------
# POST INIT
# -----------------------------
async def post_init(application: Application):
    await application.bot.set_my_commands([
        BotCommand("start", "Включить сигналы"),
        BotCommand("stop", "Выключить сигналы")
    ])
    application.create_task(mexc_ws())
    application.create_task(binance_ws())
    print("WebSockets started for MEXC and Binance!")

# -----------------------------
# RUN
# -----------------------------
if __name__ == "__main__":
    application = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stop", stop))
    application.add_handler(CommandHandler("exclude", exclude))
    application.add_handler(MessageHandler(filters.COMMAND, unknown))

    application.run_polling()
