const USD_INR_RATE = 83.5;

async function fetchDashboardData() {
    try {
        const perfRes = await fetch('/api/performance.json');
        if(perfRes.ok) {
            const perf = await perfRes.json();
            updateKPIs(perf);
        }

        const tradesRes = await fetch('/api/trades.json');
        if(tradesRes.ok) {
            const trades = await tradesRes.json();
            updateTradesTable(trades);
            renderCharts(tradesObj);
        }
    } catch (e) {
        console.error("Dashboard Sync Error:", e);
    }
}

function updateKPIs(perf) {
    const pnlUsd = perf.total_pnl_usd || 0;
    const pnlInr = pnlUsd * USD_INR_RATE;
    
    const usdEl = document.getElementById('kpi-pnl-usd');
    usdEl.textContent = `$${pnlUsd >= 0 ? '+' : ''}${pnlUsd.toFixed(2)}`;
    usdEl.className = `glow-text ${pnlUsd >= 0 ? 'profit' : 'loss'}`;
    
    const inrEl = document.getElementById('kpi-pnl-inr');
    inrEl.textContent = `₹${pnlInr >= 0 ? '+' : ''}${pnlInr.toFixed(2)}`;
    inrEl.className = `glow-text ${pnlInr >= 0 ? 'profit' : 'loss'}`;
    
    document.getElementById('kpi-winrate').textContent = `${(perf.win_rate || 0).toFixed(1)}%`;
}

function updateTradesTable(tradesObj) {
    const tbody = document.getElementById('active-trades-body');
    const trades = Object.values(tradesObj);
    
    document.getElementById('kpi-active-count').textContent = trades.length;
    
    if (trades.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" style="text-align:center; color: var(--text-muted); padding: 2rem;">No active positions.</td></tr>';
        return;
    }
    
    let html = '';
    trades.forEach(t => {
        const isBuy = t.direction === 'BUY';
        
        let pnlPct = 0;
        if(t.entry_price > 0) {
            pnlPct = isBuy ? ((t.current_price - t.entry_price)/t.entry_price)*100 : ((t.entry_price - t.current_price)/t.entry_price)*100;
        }
        
        const notional = (t.amount || 0) * t.entry_price;
        const pnlUsd = (pnlPct / 100) * notional;
        const pnlInr = pnlUsd * USD_INR_RATE;
        
        const pClass = pnlPct >= 0 ? 'val-profit' : 'val-loss';
        
        html += `
            <tr>
                <td>${t.symbol}</td>
                <td><span class="${isBuy ? 'tag-buy' : 'tag-sell'}">${t.direction}</span></td>
                <td>${t.entry_price.toFixed(4)}</td>
                <td>${t.current_price.toFixed(4)}</td>
                <td class="${pClass}">${pnlPct >= 0 ? '+' : ''}${pnlPct.toFixed(2)}%</td>
                <td class="${pClass}">₹${pnlInr >= 0 ? '+' : ''}${pnlInr.toFixed(2)}</td>
                <td style="color: var(--text-muted);">${formatDuration(t.opened_at)}</td>
            </tr>
        `;
    });
    tbody.innerHTML = html;
}

function formatDuration(unixStart) {
    if(!unixStart) return '0s';
    const seconds = Math.floor(Date.now()/1000 - unixStart);
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    if (h > 0) return `${h}h ${m}m`;
    if (m > 0) return `${m}m`;
    return `<1m`;
}

setInterval(fetchDashboardData, 5000);
fetchDashboardData();


// --- TradingView Charting Logic ---
const activeCharts = {}; // { symbol: { chart, series, domElement } }

async function fetchBinanceKlines(symbol, interval='5m', limit=100) {
    const formattedSymbol = symbol.replace('/', '');
    const url = `https://api.binance.com/api/v3/klines?symbol=${formattedSymbol}&interval=${interval}&limit=${limit}`;
    const res = await fetch(url);
    const data = await res.json();
    return data.map(d => ({
        time: d[0] / 1000,
        open: parseFloat(d[1]),
        high: parseFloat(d[2]),
        low: parseFloat(d[3]),
        close: parseFloat(d[4])
    }));
}

function createChartContainer(symbol, direction) {
    const grid = document.getElementById('charts-grid');
    document.getElementById('charts-section').style.display = 'block';
    
    const card = document.createElement('div');
    card.className = 'chart-card';
    
    const header = document.createElement('div');
    header.className = 'chart-header';
    header.innerHTML = `<span class="chart-title">${symbol}</span> <span class="chart-direction ${direction}">${direction || 'LIVE'}</span>`;
    
    const chartDiv = document.createElement('div');
    chartDiv.className = 'chart-container';
    
    card.appendChild(header);
    card.appendChild(chartDiv);
    grid.appendChild(card);
    
    const chart = LightweightCharts.createChart(chartDiv, {
        layout: { background: { type: 'solid', color: 'transparent' }, textColor: '#8b9bb4' },
        grid: { vertLines: { visible: false }, horzLines: { color: 'rgba(255, 255, 255, 0.05)' } },
        crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
        timeScale: { timeVisible: true, secondsVisible: false },
    });
    
    const candlestickSeries = chart.addCandlestickSeries({
        upColor: '#00ff88', downColor: '#ff3366', borderVisible: false, wickUpColor: '#00ff88', wickDownColor: '#ff3366'
    });
    
    return { chart, series: candlestickSeries, domElement: card };
}

async function renderCharts(tradesObj) {
    let symbolsToRender = [];
    const tradesList = Object.values(tradesObj);
    
    if (tradesList.length === 0) {
        // Default charts if no active trades
        symbolsToRender = [
            { symbol: 'BTC/USDT', direction: '' }, 
            { symbol: 'ETH/USDT', direction: '' }
        ];
    } else {
        symbolsToRender = tradesList.map(t => ({ 
            symbol: t.symbol, direction: t.direction, trade: t 
        }));
    }
    
    const grid = document.getElementById('charts-grid');
    grid.innerHTML = ''; // Clear old charts
    
    for (const item of symbolsToRender) {
        const { chart, series, domElement } = createChartContainer(item.symbol, item.direction);
        
        try {
            const klines = await fetchBinanceKlines(item.symbol);
            series.setData(klines);
            
            // Draw Trade Overlays
            if (item.trade) {
                const t = item.trade;
                
                // Entry Line
                series.createPriceLine({
                    price: t.entry_price,
                    color: '#00ff88',
                    lineWidth: 2,
                    lineStyle: LightweightCharts.LineStyle.Solid,
                    axisLabelVisible: true,
                    title: 'ENTRY',
                });
                
                // Stop Loss Line
                series.createPriceLine({
                    price: t.stop_loss,
                    color: '#ff3366',
                    lineWidth: 2,
                    lineStyle: LightweightCharts.LineStyle.Dashed,
                    axisLabelVisible: true,
                    title: 'SL',
                });
                
                // Target Line
                series.createPriceLine({
                    price: t.target,
                    color: '#00b8ff',
                    lineWidth: 2,
                    lineStyle: LightweightCharts.LineStyle.Dashed,
                    axisLabelVisible: true,
                    title: 'TP',
                });
            }
            
            chart.timeScale().fitContent();
        } catch (e) {
            console.error(`Failed to load chart for ${item.symbol}`, e);
        }
    }
}
