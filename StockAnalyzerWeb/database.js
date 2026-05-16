const sqlite3 = require('sqlite3').verbose();
const path = require('path');

const dbPath = path.resolve(__dirname, 'alerts.db');
const db = new sqlite3.Database(dbPath, (err) => {
    if (err) {
        console.error('Error opening database', err.message);
    } else {
        console.log('Connected to the SQLite database.');
        // AI Learning Schema
        db.run(`CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            ticker TEXT,
            recommendation TEXT,
            confidence INTEGER,
            price REAL,
            target REAL,
            stop_loss REAL,
            sentiment TEXT,
            reason TEXT,
            metadata TEXT,
            status TEXT DEFAULT 'PENDING', -- PENDING, SUCCESS, FAILURE
            actual_outcome REAL -- The max price reached (for BUY) or min (for SELL)
        )`, (err) => {
            if (err) {
                console.error('Error creating alerts table', err.message);
            }
        });

        // Prediction accuracy log
        db.run(`CREATE TABLE IF NOT EXISTS prediction_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            total_alerts INTEGER,
            successful INTEGER,
            failed INTEGER,
            accuracy_pct REAL,
            llm_used TEXT,
            scan_duration_ms INTEGER
        )`, (err) => {
            if (err) {
                console.error('Error creating prediction_logs table', err.message);
            }
        });
    }
});

module.exports = db;
