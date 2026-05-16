document.addEventListener('DOMContentLoaded', () => {
    fetchAlerts();
    fetchPerformance();
    fetchSystemStatus();
    
    // Auto-refresh during market hours
    setInterval(() => {
        const hour = new Date().getHours();
        if (hour >= 9 && hour < 16) {
            fetchAlerts();
            fetchPerformance();
            fetchSystemStatus();
            console.log('Market hours refresh executed.');
        }
    }, 900000); 
    
    document.getElementById('refresh-btn').addEventListener('click', async () => {
        const btn = document.getElementById('refresh-btn');
        const originalContent = btn.innerHTML;
        btn.innerHTML = '⌛ Refreshing...';
        btn.classList.add('spinning');
        
        await Promise.all([fetchAlerts(), fetchPerformance(), fetchSystemStatus()]);
        
        btn.innerHTML = originalContent;
        btn.classList.remove('spinning');
    });
    document.getElementById('start-monitor-btn').addEventListener('click', () => controlAction('/api/start-monitor', '🚀 Start Monitor'));
    document.getElementById('trigger-alert-btn').addEventListener('click', () => controlAction('/api/trigger-analysis', '🔔 Send Alert Manually'));
});

async function controlAction(url, originalText) {
    const btn = document.activeElement;
    btn.innerText = '⌛...';
    try {
        const res = await fetch(url, { method: 'POST' });
        const data = await res.json();
        alert(data.message);
    } catch(e) { alert('Action failed'); }
    btn.innerText = originalText;
}

async function fetchPerformance() {
    try {
        const res = await fetch('/api/performance');
        const data = await res.json();
        
        document.getElementById('accuracy-value').textContent = data.accuracy_pct !== 'N/A' ? `${data.accuracy_pct}%` : 'Tracking...';
        document.getElementById('total-alerts-value').textContent = data.total_alerts || 0;
        document.getElementById('wins-value').textContent = `${data.successful || 0}/${(data.successful || 0) + (data.failed || 0)}`;
        document.getElementById('avg-confidence-value').textContent = data.avg_confidence ? `${Math.round(data.avg_confidence)}%` : '--';
    } catch (e) {
        console.error('Performance fetch error:', e);
    }
}

async function fetchSystemStatus() {
    try {
        const res = await fetch('/api/status');
        const data = await res.json();
        
        const llmEl = document.getElementById('active-llm');
        if (llmEl) llmEl.textContent = data.activeLLM ? data.activeLLM.split('→')[0].trim() : 'Claude Sonnet';
        
        const lastScan = document.getElementById('last-scan-time');
        if (lastScan && data.lastScanTime) {
            const d = new Date(data.lastScanTime);
            lastScan.textContent = d.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' });
        }
        
        const scansEl = document.getElementById('scans-today');
        if (scansEl) scansEl.textContent = data.totalScansToday || 0;
    } catch (e) {
        console.error('Status fetch error:', e);
    }
}

async function fetchAlerts() {
    const grid = document.getElementById('alerts-grid');
    const reportContent = document.getElementById('report-content');

    try {
        const response = await fetch('/api/alerts');
        const data = await response.json();
        
        if (data.message === 'success' && data.data) {
            renderAlerts(data.data);
            
            // Fetch live prices for these tickers
            const tickers = data.data.map(a => a.ticker).join(',');
            if (tickers) fetchLatestPrices(tickers);

            if (data.data.length > 0) {
                const latest = data.data[0];
                const m = latest.metadata || {};
                reportContent.innerHTML = `
                    <div style="color:var(--primary); font-weight:600; margin-bottom:10px;">LATEST MARKET INSIGHT (Claude Sonnet AI)</div>
                    <p>${latest.reason}</p>
                    <div style="margin-top:10px; font-size:0.8rem; color:var(--accent);">
                        GLOBAL VWAP: ₹${m.vwap || '---'} | ACTIVE WATCHLIST: ${data.data.length} | LLM: Claude Sonnet v2
                    </div>
                `;
            }

            // Update Ticker Tape
            const trendResponse = await fetch('/api/market-trending');
            const trendObj = await trendResponse.json();
            renderTickerTape(trendObj.data);

            // Update Header Trend (using RELIANCE as a proxy if Nifty isn't explicit)
            if (trendObj.data && trendObj.data.length > 0) {
                const rel = trendObj.data.find(s => s.ticker === 'RELIANCE.NS') || trendObj.data[0];
                const color = rel.change >= 0 ? '#10b981' : '#ef4444';
                const sign = rel.change >= 0 ? '+' : '';
                document.getElementById('nifty-trend').innerHTML = `Market: <span style="color:${color}">${sign}${rel.change}%</span>`;
            }

            // Update Global Refresh Timestamp
            const now = new Date();
            const dateStr = now.toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' });
            const timeStr = now.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
            document.getElementById('last-global-update').innerText = `Last Updated: ${dateStr} | ${timeStr}`;
        }
    } catch (error) {
        console.error('Error:', error);
    }
}

function renderAlerts(alerts) {
    const grid = document.getElementById('alerts-grid');
    grid.innerHTML = '';

    alerts.forEach(alert => {
        const card = document.createElement('div');
        card.className = 'alert-card glass';
        
        const m = alert.metadata || {};
        const p = m.pivots || {};
        const confidence = alert.confidence || 0;
        const ticker = alert.ticker;
        
        const scanDate = new Date(alert.timestamp);
        const isToday = scanDate.toDateString() === new Date().toDateString();
        const dateStr = isToday ? '' : scanDate.toLocaleDateString('en-IN', { day: '2-digit', month: 'short' }) + ' ';
        
        card.innerHTML = `
            <div class="alert-type">
                <span class="type-tag ${alert.recommendation}">${alert.recommendation}</span>
                <span class="timestamp" title="Deep AI Analysis Time">AI Analysis: ${dateStr}${scanDate.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
            </div>
            
            <div style="display:flex; justify-content:space-between; align-items:flex-end; margin-bottom:0.5rem;">
                <div class="ticker-name" style="margin:0;">${ticker}</div>
                <div style="text-align:right;">
                    <div id="live-tag-${ticker.replace('.', '-')}" style="font-size:0.55rem; color:var(--accent); font-weight:700; margin-bottom:2px; display:none;">● LIVE PRICE</div>
                    <div style="font-size:0.6rem; color:var(--text-dim); text-transform:uppercase;">Price</div>
                    <div class="current-price-val" id="price-${ticker.replace('.', '-')}" style="font-size:1.1rem; font-weight:700; color:var(--primary);">₹${alert.price}</div>
                </div>
            </div>

            <div class="alert-reason-box" style="margin: 0.5rem 0; border-left: 3px solid var(--accent); padding-left:10px; background: rgba(245, 158, 11, 0.05); border-radius: 0 4px 4px 0; padding: 8px;">
                <div style="font-size:0.65rem; font-weight:700; color:var(--accent); text-transform:uppercase; margin-bottom:3px;">Claude AI Insight</div>
                <div style="font-size:0.85rem; color:var(--text); line-height:1.3; font-weight: 500;">${alert.reason}</div>
            </div>

            <div class="chart-container" style="height: 100px; margin-bottom: 0.5rem;">
                <canvas id="chart-${ticker.replace('.', '-')}-${alert.id}"></canvas>
            </div>
            
            <div class="confidence-container" style="margin: 0.5rem 0;">
                <div class="confidence-label">
                    <span>AI Confidence</span>
                    <span>${confidence}%</span>
                </div>
                <div class="confidence-bar-bg" style="height: 6px;">
                    <div class="confidence-bar-fill" style="width: ${confidence}%"></div>
                </div>
            </div>

            <div class="prediction-box" style="margin: 0.5rem 0; padding: 0.6rem;">
                <div class="prediction-title" style="font-size: 0.65rem;">🎯 AI Prediction</div>
                <div class="alert-targets" style="display: flex; justify-content: space-between; font-size: 0.8rem;">
                    <div>Tgt: <span class="buy-text">₹${alert.target || '--'}</span></div>
                    <div>SL: <span class="sell-text">₹${alert.stop_loss || '--'}</span></div>
                </div>
            </div>

            <div class="kite-widget" style="padding: 0.6rem;">
                <div class="kite-row" style="margin-bottom: 2px;"><span>VWAP</span><span class="kite-val">₹${m.vwap || '---'}</span></div>
                
                <div class="pivot-grid" style="margin-top: 0.5rem; padding-top: 0.4rem;">
                    <div class="pivot-item"><small>S1</small><div>${p.S1 || '--'}</div></div>
                    <div class="pivot-item highlight"><small>PP</small><div>${p.PP || '--'}</div></div>
                    <div class="pivot-item"><small>R1</small><div>${p.R1 || '--'}</div></div>
                </div>
            </div>
        `;
        
        grid.appendChild(card);
        renderChart(ticker, `chart-${ticker.replace('.', '-')}-${alert.id}`, alert.recommendation);
    });
}

async function fetchLatestPrices(tickers) {
    try {
        const res = await fetch(`/api/latest-prices?tickers=${tickers}`);
        const prices = await res.json();
        
        Object.keys(prices).forEach(ticker => {
            const id = ticker.replace('.', '-');
            const el = document.getElementById(`price-${id}`);
            const tag = document.getElementById(`live-tag-${id}`);
            if (el) {
                const oldPrice = parseFloat(el.innerText.replace('₹', ''));
                const newPrice = prices[ticker];
                el.innerText = `₹${newPrice.toFixed(2)}`;
                if (tag) tag.style.display = 'block';
                
                // Visual feedback for price change
                if (newPrice > oldPrice) el.style.color = 'var(--buy-text)';
                else if (newPrice < oldPrice) el.style.color = 'var(--sell-text)';
                
                setTimeout(() => { el.style.color = 'var(--primary)'; }, 2000);
            }
        });
    } catch (e) { console.error('Failed to fetch live prices', e); }
}

async function renderChart(ticker, canvasId, rec) {
    try {
        const res = await fetch(`/api/history/${ticker}`);
        const prices = await res.json();
        
        const ctx = document.getElementById(canvasId).getContext('2d');
        const color = rec === 'BUY' ? '#10b981' : rec === 'SELL' ? '#ef4444' : '#6366f1';
        
        new Chart(ctx, {
            type: 'line',
            data: {
                labels: prices.map((_, i) => i),
                datasets: [{
                    data: prices,
                    borderColor: color,
                    borderWidth: 2,
                    pointRadius: 0,
                    tension: 0.4,
                    fill: true,
                    backgroundColor: (context) => {
                        const gradient = context.chart.ctx.createLinearGradient(0, 0, 0, 120);
                        gradient.addColorStop(0, color + '44');
                        gradient.addColorStop(1, 'transparent');
                        return gradient;
                    }
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                scales: {
                    x: { display: false },
                    y: { 
                        display: false,
                        grid: { display: false }
                    }
                }
            }
        });
    } catch (e) { console.error('Chart failed', e); }
}

function renderTickerTape(trending) {
    const tape = document.getElementById('ticker-tape');
    if (!tape) return;
    tape.innerHTML = '';

    trending.forEach(stock => {
        const item = document.createElement('div');
        item.className = 'ticker-item';
        
        const changeColor = stock.change >= 0 ? 'var(--buy-text)' : 'var(--sell-text)';
        const symbol = stock.ticker.split('.')[0];
        const arrow = stock.change >= 0 ? '▲' : '▼';
        
        const details = `${stock.ticker}: Currently trading at ₹${stock.price}. Day Change: ${stock.change}%. Most active overall market trend.`;
        item.setAttribute('data-details', details);

        item.innerHTML = `
            <span class="ticker-symbol">${symbol}</span>
            <div style="display:flex; gap:8px; align-items:center;">
                <span class="ticker-price">₹${stock.price}</span>
                <span class="ticker-change" style="color: ${changeColor}; font-size: 0.65rem;">${arrow} ${Math.abs(stock.change)}%</span>
            </div>
        `;
        
        tape.appendChild(item);
    });
}
