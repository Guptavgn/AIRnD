import sqlite3
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta

class LearningEngine:
    def __init__(self, db_path='d:/AIRnD/StockAnalyzerWeb/alerts.db'):
        self.db_path = db_path

    def update_past_performance(self):
        """Check past alerts and mark them as SUCCESS or FAILURE."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                # Get pending alerts from the last 7 days
                query = "SELECT * FROM alerts WHERE status = 'PENDING' AND timestamp > datetime('now', '-7 days')"
                alerts = conn.execute(query).fetchall()
                
                if not alerts:
                    print("No pending alerts to evaluate.")
                    return

                for alert in alerts:
                    self.evaluate_alert(alert, conn)
                
                conn.commit()
        except Exception as e:
            print(f"Learning Engine Error: {e}")

    def evaluate_alert(self, alert, conn):
        ticker = alert['ticker']
        rec = alert['recommendation']
        target = alert['target']
        sl = alert['stop_loss']
        entry_time = alert['timestamp']
        
        # Fetch price movement since alert
        try:
            # yfinance only accepts YYYY-MM-DD for start dates
            date_only = entry_time.split(' ')[0]
            data = yf.download(ticker, start=date_only, interval='1h', progress=False)
            if data.empty: return

            if isinstance(data.columns, pd.MultiIndex):
                data.columns = data.columns.droplevel(1)
            
            # Filter data strictly after the alert time
            alert_dt = pd.to_datetime(entry_time).tz_localize('Asia/Kolkata')
            data = data[data.index >= alert_dt]
            if data.empty: return

            max_high = data['High'].max()
            min_low = data['Low'].min()

            status = 'PENDING'
            outcome = max_high if rec == 'BUY' else min_low

            if rec == 'BUY':
                if max_high >= target: status = 'SUCCESS'
                elif min_low <= sl: status = 'FAILURE'
            elif rec == 'SELL':
                if min_low <= target: status = 'SUCCESS'
                elif max_high >= sl: status = 'FAILURE'

            if status != 'PENDING':
                conn.execute("UPDATE alerts SET status = ?, actual_outcome = ? WHERE id = ?", (status, float(outcome), alert['id']))
                print(f"Validated {ticker} alert from {entry_time}: {status}")

        except Exception as e:
            print(f"Failed to evaluate {ticker}: {e}")

    def get_ticker_stats(self, ticker):
        """Return success rate for a ticker."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                res = conn.execute("""
                    SELECT 
                        COUNT(*) as total,
                        SUM(CASE WHEN status = 'SUCCESS' THEN 1 ELSE 0 END) as wins
                    FROM alerts WHERE ticker = ? AND status != 'PENDING'
                """, (ticker,)).fetchone()
                
                if res and res[0] > 0:
                    return (res[1] / res[0]) * 100
                return None
        except:
            return None

if __name__ == "__main__":
    le = LearningEngine()
    le.update_past_performance()
