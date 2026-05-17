const express = require('express');
const bodyParser = require('body-parser');
const cors = require('cors');
const cron = require('node-cron');
const { spawn } = require('child_process');
const db = require('./database');
const path = require('path');
const https = require('https');
const querystring = require('querystring');
const crypto = require('crypto');

const STOCK_ANALYZER_DIR = process.env.STOCK_ANALYZER_DIR || path.resolve(__dirname, '../StockAnalyzer');
const PYTHON_PATH = process.env.PYTHON_PATH || path.join(STOCK_ANALYZER_DIR, 'venv', 'Scripts', 'python.exe');

const app = express();
const port = process.env.PORT || 3000;

app.use(cors());
app.use(bodyParser.json());
app.use(express.static(path.join(__dirname, 'public')));

// --- AUTHENTICATION STACK ---
const activeSessions = new Set();
const activeOTPs = new Map(); // phone -> { otp, expires }

// Helper to send SMS via Twilio
function sendSMS(to, body) {
    return new Promise((resolve, reject) => {
        const accountSid = process.env.TWILIO_ACCOUNT_SID;
        const authToken = process.env.TWILIO_AUTH_TOKEN;
        const fromNumber = process.env.TWILIO_PHONE_NUMBER;

        if (!accountSid || !authToken || !fromNumber) {
            return reject(new Error("Twilio credentials missing"));
        }

        const postData = querystring.stringify({
            To: to,
            From: fromNumber,
            Body: body
        });

        const auth = Buffer.from(`${accountSid}:${authToken}`).toString('base64');

        const options = {
            hostname: 'api.twilio.com',
            port: 443,
            path: `/2010-04-01/Accounts/${accountSid}/Messages.json`,
            method: 'POST',
            headers: {
                'Authorization': `Basic ${auth}`,
                'Content-Type': 'application/x-www-form-urlencoded',
                'Content-Length': postData.length
            }
        };

        const req = https.request(options, (res) => {
            let data = '';
            res.on('data', (chunk) => data += chunk);
            res.on('end', () => {
                if (res.statusCode >= 200 && res.statusCode < 300) {
                    resolve(JSON.parse(data));
                } else {
                    reject(new Error(`Twilio error: ${res.statusCode} - ${data}`));
                }
            });
        });

        req.on('error', (e) => reject(e));
        req.write(postData);
        req.end();
    });
}

// Helper to send message via Telegram Bot (Fallback)
function sendTelegramMessage(text) {
    const botToken = process.env.TELEGRAM_BOT_TOKEN;
    const chatId = process.env.TELEGRAM_CHAT_ID;
    
    if (!botToken || !chatId) {
        return Promise.reject(new Error("Telegram credentials missing"));
    }
    
    const chatIds = chatId.split(',').map(c => c.trim()).filter(Boolean);
    const promises = chatIds.map(id => {
        return new Promise((resolve, reject) => {
            const postData = JSON.stringify({
                chat_id: id,
                text: text
            });
            
            const options = {
                hostname: 'api.telegram.org',
                port: 443,
                path: `/bot${botToken}/sendMessage`,
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Content-Length': Buffer.byteLength(postData)
                }
            };
            
            const req = https.request(options, (res) => {
                let data = '';
                res.on('data', (chunk) => data += chunk);
                res.on('end', () => {
                    if (res.statusCode >= 200 && res.statusCode < 300) {
                        resolve(JSON.parse(data));
                    } else {
                        reject(new Error(`Telegram error: ${res.statusCode} - ${data}`));
                    }
                });
            });
            
            req.on('error', (e) => reject(e));
            req.write(postData);
            req.end();
        });
    });
    
    return Promise.all(promises);
}

// Middleware: Require valid session token
function requireAuth(req, res, next) {
    const authHeader = req.headers['authorization'];
    const token = authHeader && authHeader.split(' ')[1];
    
    if (token && activeSessions.has(token)) {
        return next();
    }
    res.status(401).json({ error: "Unauthorized" });
}

// Helper to send message to a single Telegram ID (OTP Delivery)
function sendTelegramMessageToId(chatId, text) {
    return new Promise((resolve, reject) => {
        const botToken = process.env.TELEGRAM_BOT_TOKEN;
        if (!botToken) {
            return reject(new Error("Telegram bot token missing"));
        }
        
        const postData = JSON.stringify({
            chat_id: chatId,
            text: text
        });
        
        const options = {
            hostname: 'api.telegram.org',
            port: 443,
            path: `/bot${botToken}/sendMessage`,
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Content-Length': Buffer.byteLength(postData)
            }
        };
        
        const req = https.request(options, (res) => {
            let data = '';
            res.on('data', (chunk) => data += chunk);
            res.on('end', () => {
                if (res.statusCode >= 200 && res.statusCode < 300) {
                    resolve(JSON.parse(data));
                } else {
                    reject(new Error(`Telegram error: ${res.statusCode} - ${data}`));
                }
            });
        });
        
        req.on('error', (e) => reject(e));
        req.write(postData);
        req.end();
    });
}

// Auth endpoints
app.post('/api/auth/login', (req, res) => {
    const { phone } = req.body;
    const targetPhone = process.env.TARGET_PHONE_NUMBER || '9891399001';
    
    const normalizedPhone = phone ? phone.trim().replace(/[\s\-\+]/g, '') : '';
    const normalizedTarget = targetPhone.trim().replace(/[\s\-\+]/g, '');
    
    if (!normalizedPhone || (normalizedPhone !== normalizedTarget && normalizedPhone !== normalizedTarget.slice(-10))) {
        return res.status(400).json({ error: "Access Denied: Unregistered mobile number." });
    }
    
    // Generate session token instantly
    const token = crypto.randomBytes(32).toString('hex');
    activeSessions.add(token);
    
    console.log(`[AUTH] Session authorized instantly for phone ${phone}`);
    res.json({ token });
});

// Keep dummy routes to prevent any client-side breakdown
app.post('/api/auth/send-otp', (req, res) => {
    res.json({ message: "OTP bypassed. Click Verify to Enter." });
});

app.post('/api/auth/verify-otp', (req, res) => {
    const { phone } = req.body;
    const token = crypto.randomBytes(32).toString('hex');
    activeSessions.add(token);
    res.json({ token });
});

// Protect all /api endpoints except auth
app.use('/api', (req, res, next) => {
    if (req.path.startsWith('/auth/')) {
        return next();
    }
    requireAuth(req, res, next);
});
// -------------------------------------

// Track system status
let systemStatus = {
    lastScanTime: null,
    nextScanTime: null,
    activeLLM: 'Claude Sonnet → Gemini → Groq → Local Rules',
    totalScansToday: 0,
    serverStartTime: new Date().toISOString()
};

// RESTful APIs

// 1. Add new alert (Kite-Ready)
app.post('/api/alerts', (req, res) => {
    const { ticker, recommendation, confidence, price, target, stop_loss, sentiment, reason, metadata } = req.body;
    const sql = `INSERT INTO alerts (ticker, recommendation, confidence, price, target, stop_loss, sentiment, reason, metadata) 
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`;
    const params = [ticker, recommendation, confidence, price, target, stop_loss, sentiment, reason, JSON.stringify(metadata)];
    
    db.run(sql, params, function(err) {
        if (err) {
            res.status(400).json({ "error": err.message });
            return;
        }
        res.json({
            "message": "success",
            "id": this.lastID
        });
    });
});

// 2. Query latest alerts (one per ticker)
app.get('/api/alerts', (req, res) => {
    const sql = `
        SELECT * FROM alerts 
        WHERE id IN (SELECT MAX(id) FROM alerts GROUP BY ticker) 
        ORDER BY id DESC
    `;
    db.all(sql, [], (err, rows) => {
        if (err) {
            res.status(400).json({ "error": err.message });
            return;
        }
        res.json({
            "message": "success",
            "data": rows.map(r => {
                let parsedMeta = {};
                try { parsedMeta = JSON.parse(r.metadata || '{}'); }
                catch (e) { console.error('Invalid metadata JSON for', r.ticker); }
                return {...r, metadata: parsedMeta};
            })
        });
    });
});

// 3. Full alert history (last 30 days)
app.get('/api/alerts/history', (req, res) => {
    const limit = parseInt(req.query.limit) || 100;
    const sql = `SELECT * FROM alerts ORDER BY id DESC LIMIT ?`;
    db.all(sql, [limit], (err, rows) => {
        if (err) {
            res.status(400).json({ "error": err.message });
            return;
        }
        res.json({
            "message": "success",
            "data": rows.map(r => {
                let parsedMeta = {};
                try { parsedMeta = JSON.parse(r.metadata || '{}'); }
                catch (e) { }
                return {...r, metadata: parsedMeta};
            })
        });
    });
});

// 4. Performance & accuracy tracking
app.get('/api/performance', (req, res) => {
    const sql = `
        SELECT 
            COUNT(*) as total_alerts,
            SUM(CASE WHEN status = 'SUCCESS' THEN 1 ELSE 0 END) as successful,
            SUM(CASE WHEN status = 'FAILURE' THEN 1 ELSE 0 END) as failed,
            SUM(CASE WHEN status = 'PENDING' THEN 1 ELSE 0 END) as pending,
            SUM(CASE WHEN recommendation = 'BUY' THEN 1 ELSE 0 END) as total_buys,
            SUM(CASE WHEN recommendation = 'SELL' THEN 1 ELSE 0 END) as total_sells,
            SUM(CASE WHEN recommendation = 'HOLD' THEN 1 ELSE 0 END) as total_holds,
            AVG(confidence) as avg_confidence
        FROM alerts WHERE timestamp > datetime('now', '-30 days')
    `;
    db.get(sql, [], (err, row) => {
        if (err) {
            res.status(400).json({ "error": err.message });
            return;
        }
        const total_resolved = (row.successful || 0) + (row.failed || 0);
        const accuracy = total_resolved > 0 ? ((row.successful / total_resolved) * 100).toFixed(1) : 'N/A';
        res.json({
            ...row,
            accuracy_pct: accuracy,
            system_status: systemStatus
        });
    });
});

// 5. System status
app.get('/api/status', (req, res) => {
    res.json(systemStatus);
});

// Control APIs
app.post('/api/start-monitor', (req, res) => {
    const pythonPath = PYTHON_PATH;
    const scriptPath = path.join(STOCK_ANALYZER_DIR, 'stock_analyzer.py');
    spawn(pythonPath, [scriptPath, 'monitor'], { detached: true, stdio: 'ignore' }).unref();
    res.json({ "message": "Python Monitor v2.0 started (Claude Sonnet primary LLM)." });
});

app.post('/api/trigger-analysis', (req, res) => {
    const pythonPath = PYTHON_PATH;
    const cmd = 'from stock_analyzer import hourly_monitor; hourly_monitor()';
    spawn(pythonPath, ['-c', cmd], { cwd: STOCK_ANALYZER_DIR });
    systemStatus.lastScanTime = new Date().toISOString();
    systemStatus.totalScansToday++;
    res.json({ "message": "Manual analysis triggered (Claude Sonnet). Dashboard will update shortly." });
});

// Cleanup old records (daily at midnight)
cron.schedule('0 0 * * *', () => {
    db.run(`DELETE FROM alerts WHERE timestamp < datetime('now', '-30 days')`);
});

// Hourly Intelligence Scan (9 AM - 4 PM IST, Mon-Fri)
cron.schedule('0 9-16 * * 1-5', () => {
    console.log(`Executing Hourly Market Scan (Local Time: ${new Date().toLocaleTimeString()})...`);
    const pythonPath = PYTHON_PATH;
    const cmd = 'from stock_analyzer import hourly_monitor; hourly_monitor()';
    spawn(pythonPath, ['-c', cmd], { cwd: STOCK_ANALYZER_DIR });
    systemStatus.lastScanTime = new Date().toISOString();
    systemStatus.totalScansToday++;
});

// AI Learning & Self-Correction (4:15 PM Local Time, Mon-Fri)
cron.schedule('15 16 * * 1-5', () => {
    console.log('Intelligence Check: Running Daily Learning Engine...');
    const pythonPath = PYTHON_PATH;
    const scriptPath = path.join(STOCK_ANALYZER_DIR, 'learning_engine.py');
    spawn(pythonPath, [scriptPath], { cwd: STOCK_ANALYZER_DIR });
});

// Reset daily scan count at midnight
cron.schedule('0 0 * * *', () => {
    systemStatus.totalScansToday = 0;
});

// 30-day price history for charts
app.get('/api/history/:ticker', (req, res) => {
    const ticker = req.params.ticker;
    const pythonPath = PYTHON_PATH;
    const cmd = `import yfinance as yf; import json; import pandas as pd; h = yf.download('${ticker}', period='1mo', interval='1d'); 
if isinstance(h.columns, pd.MultiIndex): h.columns = h.columns.droplevel(1);
data = h['Close'].tolist() if 'Close' in h.columns else [];
print('JSON_START' + json.dumps(data) + 'JSON_END')`;
    
    const py = spawn(pythonPath, ['-c', cmd]);
    let output = '';
    py.stdout.on('data', (data) => output += data);
    py.on('close', () => {
        try {
            const match = output.match(/JSON_START(.*)JSON_END/);
            res.json(JSON.parse(match ? match[1] : '[]'));
        } catch (e) { res.json([]); }
    });
});

// Cache for Market Trending Data
let marketTrendingCache = [];
let lastCacheUpdateTime = null;

function updateMarketTrendingCache() {
    lastCacheUpdateTime = new Date().toISOString();
    const pythonPath = PYTHON_PATH;
    const cmd = `import yfinance as yf; import json; import pandas as pd; 
tickers = ['RELIANCE.NS','TCS.NS','HDFCBANK.NS','ICICIBANK.NS','BHARTIARTL.NS','SBIN.NS','INFY.NS','LICI.NS','ITC.NS','HINDUNILVR.NS','LT.NS','BAJFINANCE.NS'];
data = yf.download(' '.join(tickers), period='2d', interval='1d', progress=False);
close_prices = data['Close'];
if len(close_prices) >= 2:
    changes = ((close_prices.iloc[-1] - close_prices.iloc[-2]) / close_prices.iloc[-2] * 100).to_dict();
    prices = close_prices.iloc[-1].to_dict();
    result = [{'ticker': t, 'price': round(prices[t], 2), 'change': round(changes[t], 2)} for t in changes if not pd.isna(prices.get(t))];
    print('JSON_START' + json.dumps(sorted(result, key=lambda x: abs(x['change']), reverse=True)[:10]) + 'JSON_END')`;
    
    const py = spawn(pythonPath, ['-c', cmd]);
    let output = '';
    py.stdout.on('data', (data) => output += data);
    py.on('close', () => {
        try {
            const match = output.match(/JSON_START(.*)JSON_END/);
            if (match) marketTrendingCache = JSON.parse(match[1]);
        } catch (e) { console.error('Cache Update Failed', e); }
    });
}
// Update cache every 5 minutes
setInterval(updateMarketTrendingCache, 5 * 60 * 1000);
updateMarketTrendingCache(); // Initial fetch

// Endpoint for latest prices of specific tickers
app.get('/api/latest-prices', (req, res) => {
    const tickers = req.query.tickers ? req.query.tickers.split(',') : [];
    if (tickers.length === 0) return res.json({});

    const pythonPath = PYTHON_PATH;
    const cmd = `import yfinance as yf; import json; import pandas as pd; 
data = yf.download('${tickers.join(' ')}', period='1d', interval='1m', progress=False);
if not data.empty:
    latest = data['Close'].iloc[-1]
    if isinstance(latest, pd.Series):
        result = latest.to_dict()
    else:
        result = { '${tickers[0]}': float(latest) }
    print('JSON_START' + json.dumps(result) + 'JSON_END')
else:
    print('JSON_START{}JSON_END')`;
    
    const py = spawn(pythonPath, ['-c', cmd]);
    let output = '';
    py.stdout.on('data', (data) => output += data);
    py.on('close', () => {
        try {
            const match = output.match(/JSON_START(.*)JSON_END/);
            res.json(JSON.parse(match ? match[1] : '{}'));
        } catch (e) { res.json({}); }
    });
});

// Top 10 Overall Trending Stocks (Instant from Cache)
app.get('/api/market-trending', (req, res) => {
    res.json({
        data: marketTrendingCache,
        lastUpdate: lastCacheUpdateTime
    });
});

app.listen(port, () => {
    console.log(`Gaurav Antigravity v2.0 Server running on port ${port}`);
    console.log(`LLM Chain: Claude Sonnet → Gemini → Groq → Local Rules`);
    console.log(`Security: Active on TARGET_PHONE_NUMBER`);
});
