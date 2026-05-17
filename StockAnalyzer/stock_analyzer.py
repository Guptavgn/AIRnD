import yfinance as yf
import pandas as pd
import sqlite3
from textblob import TextBlob
from statsmodels.tsa.arima.model import ARIMA
import matplotlib.pyplot as plt
import warnings
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
try:
    import twilio
    from twilio.rest import Client
    TWILIO_AVAILABLE = True
except Exception:
    TWILIO_AVAILABLE = False
import os
from dotenv import load_dotenv
import urllib.parse
import urllib.request
import json
import numpy as np
from datetime import datetime
import pytz
from ml_analyzer import MLAnalyzer
from learning_engine import LearningEngine
warnings.filterwarnings('ignore')

try:
    from google import genai
    from google.genai import types
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False

try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False

try:
    from groq import Groq
    GROQ_AVAILABLE = True
except ImportError:
    GROQ_AVAILABLE = False

# Load local .env if available
load_dotenv()

class KeyManager:
    def __init__(self, key_string):
        if not key_string:
            self.keys = []
        else:
            self.keys = [k.strip() for k in key_string.split(',') if k.strip()]
        self.current_index = 0
    
    def get_key(self):
        return self.keys[self.current_index] if self.keys else None
    
    def rotate(self):
        if len(self.keys) > 1:
            self.current_index = (self.current_index + 1) % len(self.keys)
            return True
        return False

# Notification credentials
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
TWILIO_ACCOUNT_SID = os.getenv('TWILIO_ACCOUNT_SID')
TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN')
TWILIO_PHONE_NUMBER = os.getenv('TWILIO_PHONE_NUMBER')
TARGET_PHONE_NUMBER = os.getenv('TARGET_PHONE_NUMBER', '9891399001')

# API Key Managers for Rotation
GEMINI_MGR = KeyManager(os.getenv('GEMINI_API_KEY'))
GROQ_MGR = KeyManager(os.getenv('GROQ_API_KEY'))
ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY')

def sanitize_markdown(text):
    """Clean text for Telegram but preserve basic structural intent."""
    return text.replace('_', '\\_').replace('[', '').replace(']', '').replace('`', '')

class DatabaseManager:
    def __init__(self, db_path=None):
        if db_path is None:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            db_path = os.getenv('DATABASE_PATH') or os.path.abspath(os.path.join(script_dir, '..', 'StockAnalyzerWeb', 'alerts.db'))
        self.db_path = db_path
        self.init_db()

    def init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    ticker TEXT,
                    recommendation TEXT,
                    confidence INTEGER,
                    price REAL,
                    target REAL,
                    stop_loss REAL,
                    sentiment TEXT,
                    reason TEXT
                )
            ''')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_ticker ON alerts(ticker)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_timestamp ON alerts(timestamp)')

    def log_alert(self, ticker, rec_data, sentiment, metadata=None):
        try:
            local_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            with sqlite3.connect(self.db_path) as conn:
                conn.execute('''
                    INSERT INTO alerts (ticker, recommendation, confidence, price, target, stop_loss, sentiment, reason, metadata, timestamp, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING')
                ''', (
                    ticker, 
                    rec_data['recommendation'], 
                    rec_data['confidence'], 
                    rec_data['entry'], 
                    rec_data['target'], 
                    rec_data['stop_loss'], 
                    str(sentiment), 
                    rec_data['reason'],
                    json.dumps(metadata) if metadata else None,
                    local_time
                ))
                # Cleanup: Keep only last 30 days
                conn.execute("DELETE FROM alerts WHERE timestamp < datetime('now', '-30 days')")
        except Exception as e:
            print(f"Database log error: {e}")

    def get_recent_sentiment(self, ticker, days=7):
        """Analyze if alerts are consistently pointing in one direction."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                query = "SELECT recommendation FROM alerts WHERE ticker = ? AND timestamp > datetime('now', ?)"
                df = pd.read_sql_query(query, conn, params=(ticker, f'-{days} days'))
                if df.empty: return "NEUTRAL"
                counts = df['recommendation'].value_counts()
                return counts.idxmax() if not counts.empty else "NEUTRAL"
        except Exception:
            return "NEUTRAL"

class StockAnalyzer:
    def __init__(self, ticker, db=None):
        self.ticker = ticker
        self.db = db
        self.data = None
        self.learning_engine = LearningEngine()
        self.pe_ratio = "N/A"
        self.profit_margin = "N/A"
        self.news_sentiment = "N/A"

    def fetch_data(self, period='1y'):
        """Fetch historical stock data."""
        self.data = yf.download(self.ticker, period=period, interval='1d')
        if self.data.empty:
            print(f"No data for {self.ticker}")
            return
        if isinstance(self.data.columns, pd.MultiIndex):
            self.data.columns = self.data.columns.droplevel(1)
        self.data = self.data[~self.data.index.duplicated(keep='last')]
        self.data = self.data.reset_index(drop=True)  # Ensure unique integer index
        print(f"Data fetched for {self.ticker}: {len(self.data)} rows")

    def calculate_indicators(self):
        """Calculate technical indicators."""
        if self.data is None or self.data.empty:
            return
        # SMAs (MA10, MA50, MA200)
        self.data['MA10'] = self.data['Close'].rolling(window=10).mean()
        self.data['MA50'] = self.data['Close'].rolling(window=50).mean()
        self.data['MA200'] = self.data['Close'].rolling(window=200).mean()
        self.data['SMA_20'] = self.data['Close'].rolling(window=20).mean()
        
        # RSI (Wilder's Exponential Smoothing)
        delta = self.data['Close'].diff()
        gain = (delta.where(delta > 0, 0)).ewm(alpha=1/14, adjust=False).mean()
        loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/14, adjust=False).mean()
        rs = gain / loss
        self.data['RSI'] = 100 - (100 / (1 + rs))
        # MACD
        exp1 = self.data['Close'].ewm(span=12, adjust=False).mean()
        exp2 = self.data['Close'].ewm(span=26, adjust=False).mean()
        self.data['MACD'] = exp1 - exp2
        self.data['Signal_Line'] = self.data['MACD'].ewm(span=9, adjust=False).mean()
        self.data['MACD_Hist'] = self.data['MACD'] - self.data['Signal_Line']
        
        # Volume SMA
        self.data['Volume_SMA_20'] = self.data['Volume'].rolling(window=20).mean()
        
        # Bollinger Bands
        std = self.data['Close'].rolling(window=20).std()
        self.data['BB_Upper'] = self.data['SMA_20'] + (std * 2)
        self.data['BB_Lower'] = self.data['SMA_20'] - (std * 2)
        
        # ATR Calculation (14-day)
        high_low = self.data['High'] - self.data['Low']
        high_close = np.abs(self.data['High'] - self.data['Close'].shift())
        low_close = np.abs(self.data['Low'] - self.data['Close'].shift())
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        true_range = np.max(ranges, axis=1)
        self.data['ATR'] = true_range.rolling(14).mean()

        # Zerodha Kite-style Pivot Points (Standard)
        if len(self.data) > 1:
            prev = self.data.iloc[-2]
            h, l, c = prev['High'], prev['Low'], prev['Close']
            pp = (h + l + c) / 3
            self.pivots = {
                'PP': round(float(pp), 2),
                'R1': round(float(2*pp - l), 2),
                'S1': round(float(2*pp - h), 2),
                'R2': round(float(pp + (h-l)), 2),
                'S2': round(float(pp - (h-l)), 2)
            }
        
        # Candlestick Patterns (Simple Detection)
        self.data['Body'] = self.data['Close'] - self.data['Open']
        self.data['Range'] = self.data['High'] - self.data['Low']
        self.data['Doji'] = (np.abs(self.data['Body']) <= (self.data['Range'] * 0.1)).astype(int)
        
        # Risk Metrics (Beta, Sharpe, Drawdown)
        returns = self.data['Close'].pct_change().dropna()
        self.sharpe = float((returns.mean() / returns.std()) * np.sqrt(252)) if not returns.empty else 0
        
        cumulative = (1 + returns).cumprod()
        peak = cumulative.cummax()
        self.max_drawdown = float(((cumulative - peak) / peak).min() * 100) if not returns.empty else 0
        
        # Beta against Nifty (Macro Parameter)
        try:
            nifty = yf.download('^NSEI', period='1y', interval='1d', progress=False)['Close']
            n_returns = nifty.pct_change().dropna()
            combined = pd.concat([returns, n_returns], axis=1).dropna()
            self.beta = float(combined.cov().iloc[0, 1] / combined.iloc[:, 1].var())
        except: self.beta = 1.0

        # Rolling 20-Day VWAP (Institutional MVWAP)
        typical_price = (self.data['High'] + self.data['Low'] + self.data['Close']) / 3
        vp = typical_price * self.data['Volume']
        self.data['VWAP'] = vp.rolling(window=20).sum() / self.data['Volume'].rolling(window=20).sum()
        
        print(f"Expert technicals and risk metrics calculated for {self.ticker}.")

    def _extract_technicals(self):
        """Extract latest technical indicators as a dict for LLM prompt."""
        d = self.data
        close_col = d['Close']
        latest_close = float(close_col.iloc[-1, 0] if isinstance(close_col, pd.DataFrame) else close_col.iloc[-1])
        prev_close = float(close_col.iloc[-2, 0] if isinstance(close_col, pd.DataFrame) else close_col.iloc[-2]) if len(close_col) > 1 else latest_close
        def g(col): return round(float(d[col].iloc[-1]), 4) if col in d.columns and not pd.isna(d[col].iloc[-1]) else None
        return {
            'price': round(latest_close, 2), 'prev_close': round(prev_close, 2),
            'change_pct': round((latest_close - prev_close) / prev_close * 100, 2) if prev_close else 0,
            'RSI': g('RSI'), 'MACD': g('MACD'), 'Signal_Line': g('Signal_Line'), 'MACD_Hist': g('MACD_Hist'),
            'SMA_20': g('SMA_20'), 'MA10': g('MA10'), 'MA50': g('MA50'), 'MA200': g('MA200'),
            'BB_Upper': g('BB_Upper'), 'BB_Lower': g('BB_Lower'), 'ATR': g('ATR'),
            'Volume': g('Volume'), 'Volume_SMA_20': g('Volume_SMA_20'),
            'VWAP': g('VWAP'), 'Doji': int(d['Doji'].iloc[-1]) if 'Doji' in d.columns else 0,
            'pivots': self.pivots if hasattr(self, 'pivots') else {},
            'day_high': g('High'), 'day_low': g('Low'),
            'sharpe': round(self.sharpe, 2) if hasattr(self, 'sharpe') else None,
            'max_drawdown': round(self.max_drawdown, 2) if hasattr(self, 'max_drawdown') else None,
            'beta': round(self.beta, 2) if hasattr(self, 'beta') else None,
        }

    def _build_llm_prompt(self, tech, market_trend):
        """Build structured prompt for LLM financial analysis."""
        fund = self.fundamentals if hasattr(self, 'fundamentals') else {}
        macro = self.macro if hasattr(self, 'macro') else {}
        stats = self.learning_engine.get_ticker_stats(self.ticker)
        learning = f"Historical accuracy for {self.ticker}: {stats:.1f}%" if stats else "No prior accuracy data."
        return f"""You are an elite institutional-grade financial analyst. Analyze this stock and return ONLY valid JSON.

STOCK: {self.ticker}
MARKET TREND: {market_trend}

TECHNICALS:
- Price: ₹{tech['price']} (Change: {tech['change_pct']}%)
- RSI: {tech['RSI']} | MACD: {tech['MACD']} (Signal: {tech['Signal_Line']}, Hist: {tech['MACD_Hist']})
- SMA: 10={tech['MA10']}, 20={tech['SMA_20']}, 50={tech['MA50']}, 200={tech['MA200']}
- Bollinger: Upper={tech['BB_Upper']}, Lower={tech['BB_Lower']}
- ATR: {tech['ATR']} | VWAP: {tech['VWAP']}
- Volume: {tech['Volume']} (20d Avg: {tech['Volume_SMA_20']})
- Pivots: {json.dumps(tech['pivots'])}

FUNDAMENTALS:
- P/E: {fund.get('pe_ratio','N/A')} | P/B: {fund.get('pb_ratio','N/A')} | EPS: {fund.get('eps','N/A')}
- ROE: {fund.get('roe','N/A')} | D/E: {fund.get('debt_to_equity','N/A')}
- Div Yield: {fund.get('div_yield','N/A')} | Rev Growth: {fund.get('revenue_growth','N/A')}
- Analyst Rating: {fund.get('analyst_rating','N/A')}

RISK METRICS:
- Beta: {tech['beta']} | Sharpe: {tech['sharpe']} | Max Drawdown: {tech['max_drawdown']}%

MACRO & GEOPOLITICS: Gold={macro.get('Gold','N/A')}, Oil={macro.get('Oil','N/A')}, USDINR={macro.get('USDINR','N/A')}

LATEST NEWS & SENTIMENT: {self.news_sentiment}
LEARNING: {learning}

INSTRUCTIONS:
1. Synthesize real-time market scenarios, geopolitics, the latest company news, and overall sentiment with the technical/fundamental process.
2. Formulate a highly convicted confidence score (0-100). Do NOT be overly conservative. If real-time macro, news, or geopolitical factors align with the technicals, explicitly assign a confidence score between 85 and 99.
3. The "reason" field MUST be a detailed, compelling explanation that explicitly states the *most important reasons* driving your recommendation (e.g., citing specific geopolitical impacts, recent news catalysts, sentiment shifts, and confirming technical indicators). Ensure the tone is highly confident and institutional.

Return JSON with exactly these fields:
{{"recommendation": "BUY"|"SELL"|"HOLD", "confidence": 0-100, "entry": price, "target": price, "stop_loss": price, "reason": "Detailed explanation highlighting the most important real-time news, geopolitical factors, sentiment, and technicals driving this decision."}}"""

    def generate_recommendation(self, market_trend="UNKNOWN"):
        """Generate recommendation using Claude (primary) with fallback chain."""
        if self.data is None or self.data.empty:
            return None
        
        self.calculate_indicators()
        tech = self._extract_technicals()
        prompt = self._build_llm_prompt(tech, market_trend)
        
        # Attempt 1: Gemini 2.0 Flash (Free - Primary)
        rec = self._try_gemini(prompt, tech)
        if rec: return rec
        
        # Attempt 2: Groq Llama 3.3 (Free - Fallback)
        rec = self._try_groq(prompt, tech)
        if rec: return rec
        
        # Attempt 3: Claude Sonnet (Paid - if key available)
        rec = self._try_claude(prompt, tech)
        if rec: return rec
        
        # Attempt 4: Local rules engine (Final fallback)
        return self._local_rules_recommendation(tech, market_trend)

    def _try_claude(self, prompt, tech):
        """Try Claude Sonnet for recommendation."""
        if not ANTHROPIC_AVAILABLE or not ANTHROPIC_API_KEY:
            return None
        try:
            client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
            response = client.messages.create(
                model='claude-sonnet-4-20250514',
                max_tokens=500,
                messages=[{'role': 'user', 'content': prompt}]
            )
            text = response.content[0].text.strip()
            # Extract JSON from response
            if '{' in text:
                json_str = text[text.index('{'):text.rindex('}')+1]
                rec = json.loads(json_str)
                rec = self._enrich_metadata(rec, tech)
                print(f"Claude Sonnet recommendation for {self.ticker}: {rec['recommendation']}")
                return rec
        except Exception as e:
            print(f"Claude failed for {self.ticker}: {e}")
        return None

    def _try_gemini(self, prompt, tech):
        """Try Gemini models (Free - Primary LLM)."""
        if not GENAI_AVAILABLE or not GEMINI_MGR.get_key():
            return None
        models = ['gemini-2.5-flash', 'gemini-2.5-pro', 'gemini-2.0-flash']
        for model_name in models:
            for _ in range(len(GEMINI_MGR.keys) or 1):
                try:
                    client = genai.Client(api_key=GEMINI_MGR.get_key())
                    response = client.models.generate_content(
                        model=model_name, contents=prompt,
                        config=types.GenerateContentConfig(response_mime_type='application/json')
                    )
                    rec = json.loads(response.text)
                    rec = self._enrich_metadata(rec, tech)
                    print(f"Gemini ({model_name}) recommendation for {self.ticker}: {rec['recommendation']}")
                    return rec
                except Exception as e:
                    if '429' in str(e) and GEMINI_MGR.rotate(): continue
                    break
        return None

    def _try_groq(self, prompt, tech):
        """Try Groq as fallback 2."""
        if not GROQ_AVAILABLE or not GROQ_MGR.get_key():
            return None
        for _ in range(len(GROQ_MGR.keys) or 1):
            try:
                client = Groq(api_key=GROQ_MGR.get_key())
                response = client.chat.completions.create(
                    model='llama-3.3-70b-versatile',
                    messages=[{'role': 'user', 'content': prompt}],
                    response_format={"type": "json_object"}
                )
                rec = json.loads(response.choices[0].message.content)
                rec = self._enrich_metadata(rec, tech)
                print(f"Groq recommendation for {self.ticker}: {rec['recommendation']}")
                return rec
            except Exception as e:
                if '429' in str(e) and GROQ_MGR.rotate(): continue
                break
        return None

    def _local_rules_recommendation(self, tech, market_trend):
        """Local rules-based fallback when all LLMs fail."""
        entry = tech['price']
        atr = tech['ATR'] or entry * 0.05
        rsi = tech['RSI'] or 50
        macd = tech['MACD'] or 0
        signal = tech['Signal_Line'] or 0
        sma20 = tech['SMA_20'] or entry
        vol = tech['Volume'] or 0
        vol_sma = tech['Volume_SMA_20'] or 0
        rec, confidence = "HOLD", 50
        target = entry + (1.5 * atr)
        stop_loss = entry - (1.0 * atr)
        reason = f"Mixed signals at ₹{entry:.2f} (RSI:{rsi:.1f}, MACD:{macd:.2f}). HOLD recommended."
        if entry > sma20 and rsi < 70 and macd > signal and vol > vol_sma:
            rec, confidence = "BUY", 85 if market_trend != "BEARISH" else 70
            reason = f"Bullish breakout at ₹{entry:.2f}. Price above SMA20 with volume confirmation."
        elif entry < sma20 and rsi > 30 and macd < signal and vol > vol_sma:
            rec, confidence = "SELL", 85 if market_trend != "BULLISH" else 70
            reason = f"Bearish breakdown at ₹{entry:.2f}. Price below SMA20 on high volume."
        elif entry > sma20 and rsi < 70 and macd > signal:
            rec, confidence = "BUY", 60
            reason = f"Weak bullish at ₹{entry:.2f}. Rising but lacks volume. Caution."
        elif entry < sma20 and rsi > 30 and macd < signal:
            rec, confidence = "SELL", 60
            reason = f"Weak bearish at ₹{entry:.2f}. Slipping but low sell volume."
        if self.db:
            past = self.db.get_recent_sentiment(self.ticker, days=3)
            if past == rec and rec != "HOLD":
                confidence = min(100, confidence + 10)
                reason += f" [3-day {past} trend confirmed]"
        return self._enrich_metadata({'recommendation': rec, 'entry': round(entry,2), 'target': round(target,2), 'stop_loss': round(stop_loss,2), 'confidence': confidence, 'reason': reason}, tech)

    def _enrich_metadata(self, rec, tech):
        """Attach Kite-style metadata to recommendation."""
        fund = self.fundamentals if hasattr(self, 'fundamentals') else {}
        rec['metadata'] = {
            'pivots': tech.get('pivots', {}),
            'vwap': tech.get('VWAP'), 'day_high': tech.get('day_high'), 'day_low': tech.get('day_low'),
            'RSI': tech.get('RSI'), 'MACD': tech.get('MACD'),
            'MA10': tech.get('MA10'), 'MA50': tech.get('MA50'), 'MA200': tech.get('MA200'),
            'BB_Upper': tech.get('BB_Upper'), 'BB_Lower': tech.get('BB_Lower'),
            'beta': tech.get('beta'), 'sharpe': tech.get('sharpe'),
            'pe_ratio': fund.get('pe_ratio'), 'pb_ratio': fund.get('pb_ratio'),
            'roe': fund.get('roe'), 'debt_to_equity': fund.get('debt_to_equity'),
        }
        # Ensure numeric types for JSON
        import math
        for k, v in rec['metadata'].items():
            if isinstance(v, (np.float32, np.float64, np.int64, float)):
                if math.isnan(v):
                    rec['metadata'][k] = None
                else:
                    rec['metadata'][k] = float(v)
        rec['entry'] = round(float(rec.get('entry', tech['price'])), 2)
        rec['target'] = round(float(rec.get('target', tech['price'])), 2)
        rec['stop_loss'] = round(float(rec.get('stop_loss', tech['price'])), 2)
        
        # Enforce Institutional High Conviction (Scale confidence to 85-99 range for BUY/SELL)
        raw_confidence = int(rec.get('confidence', 50))
        if rec.get('recommendation') in ['BUY', 'SELL']:
            if raw_confidence < 85:
                # Mathematically scale 50-84 into 85-99
                scale_factor = (raw_confidence - 50) / 34.0 if raw_confidence > 50 else 0
                boosted_conf = int(85 + (scale_factor * 14))
                rec['confidence'] = min(99, max(85, boosted_conf))
            else:
                rec['confidence'] = min(99, raw_confidence)
        else:
            # HOLD signals can be slightly lower but still convicted
            rec['confidence'] = min(99, max(75, raw_confidence))
            
        rec['reason'] = str(rec.get('reason', 'Analysis pending.'))
        return rec

    def fetch_fundamentals(self):
        """Fetch Core, Fundamental, and Macro Parameters."""
        try:
            ticker_obj = yf.Ticker(self.ticker)
            info = ticker_obj.info
            
            self.fundamentals = {
                'pe_ratio': info.get('trailingPE', 'N/A'),
                'pb_ratio': info.get('priceToBook', 'N/A'),
                'debt_to_equity': info.get('debtToEquity', 'N/A'),
                'roe': info.get('returnOnEquity', 'N/A'),
                'div_yield': info.get('dividendYield', 'N/A'),
                'eps': info.get('trailingEps', 'N/A'),
                'revenue_growth': info.get('revenueGrowth', 'N/A'),
                'market_cap': info.get('marketCap', 'N/A'),
                'analyst_rating': info.get('recommendationKey', 'N/A')
            }
            
            # Fetch Macro Data
            macro_tickers = {'Gold': 'GC=F', 'Oil': 'CL=F', 'USDINR': 'INR=X', '10Y_Yield': '^TNX'}
            self.macro = {}
            for label, sym in macro_tickers.items():
                try: self.macro[label] = yf.download(sym, period='1d', progress=False)['Close'].iloc[-1]
                except: self.macro[label] = 'N/A'
            
            # Fetch news
            news = ticker_obj.news
            headlines = [n.get('content', {}).get('title') for n in news[:5] if n.get('content', {}).get('title')] if news else []
            self.analyze_news_sentiment(headlines)
        except Exception as e:
            print(f"Fundamentals/Macro fetch failed for {self.ticker}: {e}")

    def analyze_news_sentiment(self, headlines):
        if not headlines:
            self.news_sentiment = "No recent news."
            return
            
        combined_news = ". ".join(headlines)
        
        # Self-Learning Injection
        stats = self.learning_engine.get_ticker_stats(self.ticker)
        learning_context = f" Your historical accuracy for {self.ticker} is {stats:.1f}%. " if stats else ""
        prompt = f"### FINANCIAL NEWS ANALYST ###\nStock: {self.ticker}\nHeadlines: {combined_news}\n{learning_context}\nTask: Analyze sentiment (1-100) and explain why in 1 sentence. Be ultra-concise. Return: [Score] - [Reason]"
        
        # Use Groq exclusively for News Sentiment processing
        if GROQ_AVAILABLE and GROQ_MGR.get_key():
            for attempt in range(len(GROQ_MGR.keys) or 1):
                try:
                    client = Groq(api_key=GROQ_MGR.get_key())
                    response = client.chat.completions.create(
                        model='llama-3.3-70b-versatile',
                        messages=[{'role': 'system', 'content': 'You are a wall street news analyst.'}, {'role': 'user', 'content': prompt}],
                        max_tokens=150
                    )
                    self.news_sentiment = sanitize_markdown(response.choices[0].message.content.strip())
                    return
                except Exception as e:
                    if "429" in str(e) and GROQ_MGR.rotate(): continue
                    break
        
        # Fallback to Gemini if Groq is down
        if GENAI_AVAILABLE and GEMINI_MGR.get_key():
            try:
                client = genai.Client(api_key=GEMINI_MGR.get_key())
                response = client.models.generate_content(model='gemini-2.0-flash-lite', contents=prompt)
                self.news_sentiment = sanitize_markdown(response.text.strip())
            except Exception:
                self.news_sentiment = f"Sentiment fallback (polarity): {self.sentiment_analysis(combined_news):.2f}"

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

def delete_previous_telegram_messages():
    """Delete previously sent messages to keep the chats clean."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID: return
    try:
        if os.path.exists('telegram_msg_ids.json'):
            with open('telegram_msg_ids.json', 'r') as f:
                msg_data = json.load(f)
            for item in msg_data:
                # Handle old format (simple integer) vs new format (list/tuple of [chat_id, msg_id])
                if isinstance(item, list) or isinstance(item, tuple):
                    chat_id, msg_id = item
                else:
                    chat_id = TELEGRAM_CHAT_ID.split(',')[0].strip() # Fallback to first chat ID
                    msg_id = item
                
                url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/deleteMessage"
                data = urllib.parse.urlencode({'chat_id': chat_id, 'message_id': msg_id}).encode('utf-8')
                try: urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=5)
                except: pass
            os.remove('telegram_msg_ids.json')
    except Exception as e:
        pass

def send_telegram_message(message):
    """Send notification via Telegram bot to all configured chat IDs and track message IDs."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False
    
    # Support multiple comma-separated chat IDs
    chat_ids = [c.strip() for c in TELEGRAM_CHAT_ID.split(',') if c.strip()]
    success = False
    
    for chat_id in chat_ids:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            data = urllib.parse.urlencode({
                'chat_id': chat_id,
                'text': message,
                'parse_mode': 'HTML'
            }).encode('utf-8')
            request = urllib.request.Request(url, data=data)
            with urllib.request.urlopen(request, timeout=15) as response:
                result = json.loads(response.read().decode('utf-8'))
            if result.get('ok'):
                msg_id = result['result']['message_id']
                try:
                    ids = []
                    if os.path.exists('telegram_msg_ids.json'):
                        with open('telegram_msg_ids.json', 'r') as f: ids = json.load(f)
                    ids.append([chat_id, msg_id])
                    with open('telegram_msg_ids.json', 'w') as f: json.dump(ids, f)
                except: pass
                print(f"Telegram message sent to {chat_id}.")
                success = True
            else:
                print(f"Telegram send failed for {chat_id}:", result)
        except Exception as e:
            print(f"Telegram send error for {chat_id}:", e)
            
    return success


def send_notification(message):
    """Send notification via Telegram first, or Twilio WhatsApp as fallback."""
    if send_telegram_message(message):
        return
    if not TWILIO_AVAILABLE or not all([TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER]):
        safe_msg = message.encode('ascii', 'replace').decode('ascii')
        print("Notification service not configured. Simulating message:", safe_msg)
        return
    try:
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        client.messages.create(
            body=message,
            from_=f'whatsapp:{TWILIO_PHONE_NUMBER}',
            to=f'whatsapp:{TARGET_PHONE_NUMBER}'
        )
        print("WhatsApp message sent via Twilio.")
    except Exception as e:
        print("Twilio send error:", e)
        safe_msg = message.encode('ascii', 'replace').decode('ascii')
        print("Simulating message:", safe_msg)

def get_market_overview():
    """Get global market context (Nifty 50)."""
    try:
        nifty_df = yf.download('^NSEI', period='1d', interval='1m', progress=False)
        vix_df = yf.download('^INDIAVIX', period='1d', interval='1m', progress=False)
        
        nifty_close = nifty_df['Close'].iloc[-1].item() if not nifty_df.empty else 0
        vix_close = vix_df['Close'].iloc[-1].item() if not vix_df.empty else 0
        
        return f"📊 Nifty 50: {nifty_close:.2f} | VIX: {vix_close:.2f}"
    except Exception as e:
        print("Market overview error:", e)
        return "📊 Market Data Refreshing..."

def hourly_monitor(ignore_weekend=False):
    """Gaurav Antigravity: Deep Intelligence Relay (Hourly: 9 AM - 4 PM IST, Mon-Fri)."""
    now = datetime.now(pytz.timezone('Asia/Kolkata'))
    if now.weekday() >= 5 and not ignore_weekend:  # Skip weekends
        print(f"Weekend skip: {now.strftime('%A %Y-%m-%d %H:%M')}")
        return
    print(f"--- Running Deep Intelligence Relay: {now.strftime('%Y-%m-%d %H:%M:%S')} ---")
    
    # 1. Delete previous alert messages to clean up the Telegram channel
    delete_previous_telegram_messages()
    
    stocks_df = load_stocks()
    if stocks_df.empty: return
    
    db_mgr = DatabaseManager()
    market_overview = get_market_overview()
    report_header = f"🌐 <b>MARKET COMMAND CENTER</b> 🌐\n{market_overview}\n{'-'*25}"
    send_notification(report_header)
    
    results = []
    
    for _, row in stocks_df.iterrows():
        ticker = row['Ticker']
        try:
            analyzer = StockAnalyzer(ticker, db=db_mgr)
            analyzer.fetch_data('1y')
            if analyzer.data is None or len(analyzer.data) < 2: continue
                
            analyzer.fetch_fundamentals()
            rec = analyzer.generate_recommendation(market_trend=market_overview)
            
            if rec:
                db_mgr.log_alert(ticker, rec, analyzer.news_sentiment, metadata=rec.get('metadata'))
                
                # Append to results for Top 5 CSV
                rec['ticker'] = ticker
                results.append(rec)
                
                # CRISP ACTIONABLE FORMAT
                emoji = "🟢 <b>BUY</b>" if rec['recommendation'] == 'BUY' else "🔴 <b>SELL</b>" if rec['recommendation'] == 'SELL' else "🟡 <b>HOLD</b>"
                
                msg = f"{emoji}: <b>{ticker}</b> (Conf: {rec['confidence']}%)\n"
                msg += f"💰 Entry: ₹{rec['entry']:.2f} | 🎯 Tgt: ₹{rec['target']:.2f} | 🛑 SL: ₹{rec['stop_loss']:.2f}\n"
                
                # Sanitize reason to avoid HTML tags and unescaped ampersands
                safe_reason = str(rec['reason']).replace('<', '').replace('>', '').replace('&', 'and')
                msg += f"🧠 <b>Reason:</b> {safe_reason}\n"
                
                # Next relay time
                next_hour = datetime.now(pytz.timezone('Asia/Kolkata')).replace(minute=0, second=0) + pd.Timedelta(hours=1)
                if next_hour.hour <= 16:
                    msg += f"⏰ <b>Next relay:</b> {next_hour.strftime('%I:%M %p')} IST"
                else:
                    msg += f"⏰ <b>Next relay:</b> Tomorrow 9:00 AM IST"
                
                send_notification(msg)
                
        except Exception as e:
            print(f"Dossier Error for {ticker}: {e}")
            
    # 3. Include top 5 stocks in CSV based on highest confidence
    if results:
        # Sort results descending by confidence
        sorted_results = sorted(results, key=lambda x: x.get('confidence', 0), reverse=True)
        top_5 = sorted_results[:5]
        try:
            # Flatten dictionary for CSV
            csv_data = []
            for rec in top_5:
                csv_data.append({
                    'Ticker': rec.get('ticker'),
                    'Recommendation': rec.get('recommendation'),
                    'Confidence': rec.get('confidence'),
                    'Entry_Price': rec.get('entry'),
                    'Target': rec.get('target'),
                    'Stop_Loss': rec.get('stop_loss'),
                    'AI_Reasoning': rec.get('reason')
                })
            df = pd.DataFrame(csv_data)
            df.to_csv('top_5_recommendations.csv', index=False)
            print("top_5_recommendations.csv updated successfully.")
        except Exception as e:
            print(f"Failed to write Top 5 CSV: {e}")
            
    print("Relay complete.")

def check_alerts():
    """Volatility and Anomaly Detection (Run frequently)."""
    try:
        stocks_df = load_stocks()
        db = DatabaseManager()
        for _, row in stocks_df.iterrows():
            ticker = row['Ticker']
            analyzer = StockAnalyzer(ticker, db=db)
            analyzer.fetch_data('1d')
            analyzer.calculate_indicators()
            
            # Simple threshold for volatility alert
            if abs(analyzer.data['Close'].pct_change().iloc[-1]) > 0.03:
                msg = f"🚨 <b>VOLATILITY ALERT: {ticker}</b> 🚨\nPrice moved > 3% recently. Checking AI sentiment..."
                send_notification(msg)
    except: pass

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

def daily_ml_report():
    """Run end-of-day ML analysis and send dashboard."""
    try:
        analyzer = MLAnalyzer()
        dashboard_msg = analyzer.generate_dashboard()
        send_notification(dashboard_msg)
    except Exception as e:
        print(f"Error in daily_ml_report: {e}")

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == 'monitor':
        scheduler = BlockingScheduler(timezone=pytz.timezone('Asia/Kolkata'))
        
        # HOURLY DEEP DOSSIERS (9 AM - 4 PM IST, Mon-Fri)
        scheduler.add_job(hourly_monitor, CronTrigger(hour='9-16', minute='0', day_of_week='mon-fri'))
        
        # Anomaly detection (Every 30 min during market hours, Mon-Fri)
        scheduler.add_job(check_alerts, CronTrigger(hour='9-15', minute='30', day_of_week='mon-fri'))
        
        # End of Day ML Report (Daily at 4:15 PM, Mon-Fri)
        scheduler.add_job(daily_ml_report, CronTrigger(hour='16', minute='15', day_of_week='mon-fri'))
        
        print("Gaurav Antigravity Autonomous Agent v2.0 Started.")
        print("Scheduled: Hourly Reports (9-16 IST Mon-Fri) + EOD Intelligence at 16:15.")
        print("Primary LLM: Gemini 2.5 Flash (Free) | Fallback: Groq -> Local Rules")
        scheduler.start()
    else:
        # Interactive mode
        stocks_df = load_stocks()
        ticker = select_stock(stocks_df)
        if ticker:
            analyzer = StockAnalyzer(ticker)
            analyzer.fetch_data()
            analyzer.fetch_fundamentals()
            print(f"Analysis for {ticker}: {analyzer.generate_recommendation()}")