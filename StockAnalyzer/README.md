# StockAnalyzer

A basic AI-driven stock analysis application (MVP).

## Features

- Fetch historical stock data
- Technical indicators (SMA, RSI, MACD)
- Buy/Sell/Hold recommendations with entry/target/stop loss
- Sentiment analysis
- Data visualization
- Daily monitoring with WhatsApp notifications at 1:45 PM IST
- Real-time alerts for significant movements

## Setup

- Add/edit stocks in `stocks.csv` (columns: Ticker, Name)
- For WhatsApp: Set environment variables: TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER
- Run interactive: `python stock_analyzer.py`
- Run daily monitor: `python stock_analyzer.py monitor` (schedules at 1:45 PM IST daily, alerts every 30 min)

## Installation

1. Install dependencies: `pip install -r requirements.txt`
2. Set Twilio env vars
3. Run the script

## Usage

- Interactive: Select stock to study
- Monitor: Sends daily WhatsApp with recommendations for all stocks
- Alerts: Sends WhatsApp for significant price movements (>5%)

## Architecture

- Data Ingestion: yfinance API
- Processing: Pandas for indicators
- Scheduling: APScheduler
- Notifications: Twilio WhatsApp API
- Deployment: Run as Python script on server/cloud instance