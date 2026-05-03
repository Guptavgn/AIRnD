import yfinance as yf
import pandas as pd
from textblob import TextBlob
from statsmodels.tsa.arima.model import ARIMA
import matplotlib.pyplot as plt
import warnings
warnings.filterwarnings('ignore')

class StockAnalyzer:
    def __init__(self, ticker):
        self.ticker = ticker
        self.data = None

    def fetch_data(self, period='1y'):
        """Fetch historical stock data."""
        self.data = yf.download(self.ticker, period=period)
        print(f"Data fetched for {self.ticker}: {len(self.data)} rows")

    def analyze_financials(self):
        """Basic financial analysis."""
        if self.data is None:
            print("No data available. Fetch data first.")
            return
        self.data['Returns'] = self.data['Close'].pct_change()
        self.data['SMA_20'] = self.data['Close'].rolling(window=20).mean()
        self.data['SMA_50'] = self.data['Close'].rolling(window=50).mean()
        print("Basic analysis completed: Returns and Moving Averages calculated.")

    def sentiment_analysis(self, text):
        """Simple sentiment analysis on text."""
        blob = TextBlob(text)
        sentiment = blob.sentiment.polarity
        print(f"Sentiment score for text: {sentiment}")
        return sentiment

    def predict_price(self, steps=5):
        """Simple ARIMA prediction."""
        if self.data is None:
            print("No data available. Fetch data first.")
            return
        model = ARIMA(self.data['Close'], order=(5,1,0))
        model_fit = model.fit()
        forecast = model_fit.forecast(steps=steps)
        print(f"Predicted prices for next {steps} days: {forecast.values}")
        return forecast

    def plot_data(self):
        """Plot stock data."""
        if self.data is None:
            print("No data available. Fetch data first.")
            return
        plt.figure(figsize=(10,5))
        plt.plot(self.data['Close'], label='Close Price')
        plt.plot(self.data['SMA_20'], label='SMA 20')
        plt.plot(self.data['SMA_50'], label='SMA 50')
        plt.title(f'{self.ticker} Stock Analysis')
        plt.legend()
        plt.savefig('stock_analysis.png')
        print("Plot saved as stock_analysis.png")

def load_stocks():
    """Load stocks from CSV."""
    try:
        df = pd.read_csv('stocks.csv')
        return df
    except FileNotFoundError:
        print("stocks.csv not found.")
        return pd.DataFrame()

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
    stocks_df = load_stocks()
    if stocks_df.empty:
        print("No stocks loaded.")
        exit()
    ticker = select_stock(stocks_df)
    if ticker:
        analyzer = StockAnalyzer(ticker)
        analyzer.fetch_data()
        analyzer.analyze_financials()
        analyzer.sentiment_analysis("Apple reported strong earnings growth.")
        analyzer.predict_price()
        analyzer.plot_data()