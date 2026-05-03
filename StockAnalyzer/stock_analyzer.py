import yfinance as yf
import pandas as pd
from textblob import TextBlob
from statsmodels.tsa.arima.model import ARIMA
import matplotlib.pyplot as plt
import warnings
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
try:
    from twilio.rest import Client
    TWILIO_AVAILABLE = True
except ImportError:
    TWILIO_AVAILABLE = False
import os
import numpy as np
from datetime import datetime
import pytz
warnings.filterwarnings('ignore')

# Twilio credentials (set as environment variables)
TWILIO_ACCOUNT_SID = os.getenv('TWILIO_ACCOUNT_SID')
TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN')
TWILIO_PHONE_NUMBER = os.getenv('TWILIO_PHONE_NUMBER')
TARGET_PHONE_NUMBER = '+919891399001'  # User's number

class StockAnalyzer:
    def __init__(self, ticker):
        self.ticker = ticker
        self.data = None

    def fetch_data(self, period='1y'):
        """Fetch historical stock data."""
        self.data = yf.download(self.ticker, period=period, interval='1d')
        if self.data.empty:
            print(f"No data for {self.ticker}")
            return
        self.data = self.data[~self.data.index.duplicated(keep='last')]
        print(f"Data fetched for {self.ticker}: {len(self.data)} rows")

    def calculate_indicators(self):
        """Calculate technical indicators."""
        if self.data is None or self.data.empty:
            return
        # SMA
        self.data['SMA_20'] = self.data['Close'].rolling(window=20).mean()
        self.data['SMA_50'] = self.data['Close'].rolling(window=50).mean()
        # RSI
        delta = self.data['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        self.data['RSI'] = 100 - (100 / (1 + rs))
        # MACD
        exp1 = self.data['Close'].ewm(span=12, adjust=False).mean()
        exp2 = self.data['Close'].ewm(span=26, adjust=False).mean()
        self.data['MACD'] = exp1 - exp2
        self.data['Signal_Line'] = self.data['MACD'].ewm(span=9, adjust=False).mean()
        self.data['MACD_Hist'] = self.data['MACD'] - self.data['Signal_Line']
        print("Indicators calculated.")

    def generate_recommendation(self):
        """Generate buy/sell/hold with details."""
        if self.data is None or self.data.empty:
            return None
        latest = dict(zip(self.data.columns, self.data.iloc[-1].values))
        prev = dict(zip(self.data.columns, self.data.iloc[-2].values)) if len(self.data) > 1 else latest
        price_change = (latest.get('Close', 0) - prev.get('Close', 0)) / prev.get('Close', 0) * 100 if len(self.data) > 1 and prev.get('Close', 0) != 0 else 0

        # Simple rule-based
        rec = "HOLD"
        confidence = 50
        entry = latest.get('Close', 0)
        target = entry * 1.05  # 5% target
        stop_loss = entry * 0.95  # 5% stop
        reason = "Neutral signals."

        # if len(self.data) < 50 or not pd.notna(latest['SMA_20']) or not pd.notna(latest['RSI']) or not pd.notna(latest['MACD']):
        #     return {
        #         'recommendation': "HOLD",
        #         'entry': entry,
        #         'target': target,
        #         'stop_loss': stop_loss,
        #         'confidence': 0,
        #         'reason': "Insufficient data for indicators."
        #     }

        if latest.get('Close', 0) > latest.get('SMA_20', 0) and latest.get('RSI', 100) < 70 and latest.get('MACD', 0) > latest.get('Signal_Line', 0):
            rec = "BUY"
            confidence = 70
            reason = "Price above SMA, RSI not overbought, MACD bullish."
        elif latest.get('Close', 0) < latest.get('SMA_20', 0) and latest.get('RSI', 0) > 30 and latest.get('MACD', 0) < latest.get('Signal_Line', 0):
            rec = "SELL"
            confidence = 70
            reason = "Price below SMA, RSI not oversold, MACD bearish."
        elif abs(price_change) > 5:
            rec = "ALERT"
            confidence = 80
            reason = f"Significant price movement: {price_change:.2f}%"

        return {
            'recommendation': rec,
            'entry': entry,
            'target': target,
            'stop_loss': stop_loss,
            'confidence': confidence,
            'reason': reason
        }

    def sentiment_analysis(self, text="Sample news"):
        """Simple sentiment analysis."""
        blob = TextBlob(text)
        return blob.sentiment.polarity

def load_stocks():
    """Load stocks from CSV."""
    try:
        df = pd.read_csv('stocks.csv')
        return df
    except FileNotFoundError:
        print("stocks.csv not found.")
        return pd.DataFrame()

def send_whatsapp_message(message):
    """Send WhatsApp message via Twilio."""
    if not TWILIO_AVAILABLE or not all([TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER]):
        print("Twilio not available or credentials not set. Simulating message:", message)
        return
    client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    client.messages.create(
        body=message,
        from_=f'whatsapp:{TWILIO_PHONE_NUMBER}',
        to=f'whatsapp:{TARGET_PHONE_NUMBER}'
    )
    print("Message sent:", message)

def daily_monitor():
    """Daily monitoring job at 1:45 PM IST."""
    ist = pytz.timezone('Asia/Kolkata')
    now = datetime.now(ist)
    if now.hour == 13 and now.minute >= 45:  # Ensure it's around 1:45 PM
        stocks_df = load_stocks()
        if stocks_df.empty:
            return
        messages = []
        for _, row in stocks_df.iterrows():
            ticker = row['Ticker']
            analyzer = StockAnalyzer(ticker)
            analyzer.fetch_data('3mo')  # Recent data
            analyzer.calculate_indicators()
            rec = analyzer.generate_recommendation()
            if rec:
                msg = f"Stock: {ticker}\nRecommendation: {rec['recommendation']}\nEntry: ₹{rec['entry']:.2f}\nTarget: ₹{rec['target']:.2f}\nStop Loss: ₹{rec['stop_loss']:.2f}\nConfidence: {rec['confidence']}%\nReason: {rec['reason']}"
                messages.append(msg)
        full_message = "\n\n".join(messages)
        send_whatsapp_message(full_message)

def check_alerts():
    """Check for significant movements (run frequently)."""
    stocks_df = load_stocks()
    for _, row in stocks_df.iterrows():
        ticker = row['Ticker']
        analyzer = StockAnalyzer(ticker)
        analyzer.fetch_data('5d')
        analyzer.calculate_indicators()
        rec = analyzer.generate_recommendation()
        if rec and rec['recommendation'] == 'ALERT':
            msg = f"ALERT: {ticker}\n{rec['reason']}"
            send_whatsapp_message(msg)

def select_stock(stocks_df):
    """Display stocks and let user select."""
    print("Available stocks:")
    for idx, row in stocks_df.iterrows():
        print(f"{idx+1}. {row['Ticker']} - {row['Name']}")
    choice = int(input("Enter the number of the stock to analyze: ")) - 1
    if 0 <= choice < len(stocks_df):
        return stocks_df.iloc[choice]['Ticker']
    else:
        print("Invalid choice.")
        return None

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == 'monitor':
        # Run scheduler for daily monitoring
        scheduler = BlockingScheduler(timezone=pytz.timezone('Asia/Kolkata'))
        scheduler.add_job(daily_monitor, CronTrigger(hour=13, minute=45))
        scheduler.add_job(check_alerts, 'interval', minutes=30)  # Check every 30 min for alerts
        print("Scheduler started. Monitoring daily at 1:45 PM IST and alerts every 30 min.")
        scheduler.start()
    else:
        # Interactive mode
        stocks_df = load_stocks()
        if stocks_df.empty:
            print("No stocks loaded.")
            exit()
        ticker = select_stock(stocks_df)
        if ticker:
            analyzer = StockAnalyzer(ticker)
            analyzer.fetch_data()
            analyzer.calculate_indicators()
            rec = analyzer.generate_recommendation()
            print(f"Recommendation: {rec}")
            analyzer.sentiment_analysis("Apple reported strong earnings growth.")