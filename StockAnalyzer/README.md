# StockAnalyzer

A basic AI-driven stock analysis application (MVP).

## Features

- Fetch historical stock data
- Technical indicators (SMA, RSI, MACD)
- Buy/Sell/Hold recommendations with entry/target/stop loss
- Sentiment analysis
- Data visualization
- Daily monitoring with Telegram notifications at 9:30 AM IST
- Real-time alerts for significant movements

## Setup

- Add/edit stocks in `stocks.csv` (columns: Ticker, Name)
- For free notifications: set environment variables or a `.env` file with `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`
- Optional Twilio fallback: `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_PHONE_NUMBER`
- Run interactive: `python stock_analyzer.py`
- Run daily monitor: `python stock_analyzer.py monitor` (schedules at 9:30 AM IST daily, alerts every 30 min)

## Installation

1. Install dependencies: `pip install -r requirements.txt`
2. Create a `.env` file with Telegram credentials or set environment variables directly
3. Run the script

## Telegram Bot Setup

1. Open Telegram and chat with `@BotFather`
2. Send `/newbot` and follow the instructions to create a new bot
3. Copy the bot token and set `TELEGRAM_BOT_TOKEN`
4. Send a message to your bot from your user account
5. Run `python telegram_chat_id_helper.py` to fetch the chat ID
6. Set `TELEGRAM_CHAT_ID` to the value shown by the helper

## .env Example

Create a `.env` file in the project root with:

```
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
```

## Usage

- Interactive: Select stock to study
- Monitor: Sends daily notifications with recommendations for all stocks
- Alerts: Sends notifications for significant price movements (>5%)

## Architecture

- Data Ingestion: yfinance API
- Processing: Pandas for indicators
- Scheduling: APScheduler
- Notifications: Telegram bot (free) with optional Twilio WhatsApp fallback
- Deployment: Run as Python script on server/cloud instance