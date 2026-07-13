
// GLOBAL ERROR HANDLER FOR DEBUGGING
window.addEventListener('error', function(e) {
    const errDiv = document.createElement('div');
    errDiv.style = "background: red; color: white; padding: 20px; z-index: 9999; font-size: 16px;";
    errDiv.textContent = "JS ERROR: " + e.message + " at " + e.filename + ":" + e.lineno;
    document.body.prepend(errDiv);
});
window.addEventListener('unhandledrejection', function(e) {
    const errDiv = document.createElement('div');
    errDiv.style = "background: orange; color: white; padding: 20px; z-index: 9999; font-size: 16px;";
    errDiv.textContent = "PROMISE ERROR: " + (e.reason ? (e.reason.message || e.reason) : e);
    if(e.reason && e.reason.stack) {
        errDiv.textContent += " | STACK: " + e.reason.stack.substring(0, 200);
    }
    document.body.prepend(errDiv);
});

const USD_INR_RATE = 83.5;

let currentSymbolsKey = null;

async function fetchDashboardData() {
    try {
        const perfRes = await fetch('/api/performance.json');
        if(perfRes.ok) {
            const perf = await perfRes.json();
            updateKPIs(perf);
        }

        const tradesRes = await fetch('/api/trades.json');
        let trades = {};
        if(tradesRes.ok) {
            trades = await tradesRes.json();
        }
        updateTradesTable(trades);
        
        // Only re-render charts if the active trade symbols have changed
        let newSymbolsKey = Object.keys(trades).sort().join(',');
        if (newSymbolsKey === "") newSymbolsKey = "default";
        
        if (newSymbolsKey !== currentSymbolsKey) {
            currentSymbolsKey = newSymbolsKey;
            renderCharts(trades);
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

function calculateEMA(data, period) {
    const k = 2 / (period + 1);
    let emaData = [];
    if(data.length === 0) return emaData;
    let ema = data[0].close;
    for (let i = 0; i < data.length; i++) {
        ema = (data[i].close - ema) * k + ema;
        emaData.push({ time: data[i].time, value: ema });
    }
    return emaData;
}

async function fetchBinanceKlines(symbol, interval='5m', limit=250) {
    const formattedSymbol = symbol.replace('/', '');
    const url = `/api/klines?symbol=${formattedSymbol}&interval=${interval}&limit=${limit}`;
    const res = await fetch(url);
    const data = await res.json();
    return data.map(d => ({
        time: d[0] / 1000,
        open: parseFloat(d[1]),
        high: parseFloat(d[2]),
        low: parseFloat(d[3]),
        close: parseFloat(d[4]),
        value: parseFloat(d[5]), // Volume
        color: parseFloat(d[4]) >= parseFloat(d[1]) ? 'rgba(0, 255, 136, 0.4)' : 'rgba(255, 51, 102, 0.4)'
    }));
}

function createChartContainer(symbol, direction) {
    const grid = document.getElementById('charts-grid');
    document.getElementById('charts-section').style.display = 'block';
    
    const card = document.createElement('div');
    card.className = 'chart-card';
    
    const header = document.createElement('div');
    header.className = 'chart-header';
    header.innerHTML = `<div><span class="chart-title">${symbol}</span> <span class="chart-direction ${direction}">${direction || 'LIVE'}</span></div>`;
    
    const maxBtn = document.createElement('button');
    maxBtn.className = 'maximize-btn';
    maxBtn.innerHTML = '⛶ Maximize';
    maxBtn.onclick = () => {
        card.classList.toggle('fullscreen');
        if (card.classList.contains('fullscreen')) {
            maxBtn.innerHTML = '🗗 Restore';
            document.body.style.overflow = 'hidden';
        } else {
            maxBtn.innerHTML = '⛶ Maximize';
            document.body.style.overflow = 'auto';
        }
    };
    header.appendChild(maxBtn);
    
    const chartDiv = document.createElement('div');
    chartDiv.className = 'chart-container';
    chartDiv.style.position = 'relative'; // For floating legend
    
    const legend = document.createElement('div');
    legend.className = 'floating-legend';
    legend.innerHTML = `${symbol} <br/> O<span class="legend-value">--</span> H<span class="legend-value">--</span> L<span class="legend-value">--</span> C<span class="legend-value">--</span> V<span class="legend-value">--</span>`;
    chartDiv.appendChild(legend);
    
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
    
    const volumeSeries = chart.addHistogramSeries({
        priceFormat: { type: 'volume' },
        priceScaleId: '', // Overlay at bottom
        scaleMargins: { top: 0.8, bottom: 0 },
    });
    
    const ema50Series = chart.addLineSeries({ color: '#ff9900', lineWidth: 2, title: 'EMA(50)' });
    const ema200Series = chart.addLineSeries({ color: '#b366ff', lineWidth: 2, title: 'EMA(200)' });
    
    // Crosshair Sync for Legend
    chart.subscribeCrosshairMove((param) => {
        if (param.point === undefined || !param.time || param.point.x < 0 || param.point.x > chartDiv.clientWidth || param.point.y < 0 || param.point.y > chartDiv.clientHeight) {
            legend.innerHTML = `${symbol} <br/> O<span class="legend-value">--</span> H<span class="legend-value">--</span> L<span class="legend-value">--</span> C<span class="legend-value">--</span> V<span class="legend-value">--</span>`;
            return;
        }
        
        const candleData = param.seriesData.get(candlestickSeries);
        const volData = param.seriesData.get(volumeSeries);
        
        if (candleData) {
            const isGreen = candleData.close >= candleData.open;
            const cClass = isGreen ? 'legend-profit' : 'legend-loss';
            legend.innerHTML = `${symbol} <br/> 
                O <span class="legend-value ${cClass}">${candleData.open.toFixed(2)}</span> 
                H <span class="legend-value ${cClass}">${candleData.high.toFixed(2)}</span> 
                L <span class="legend-value ${cClass}">${candleData.low.toFixed(2)}</span> 
                C <span class="legend-value ${cClass}">${candleData.close.toFixed(2)}</span> 
                V <span class="legend-value">${volData ? volData.value.toFixed(2) : '--'}</span>`;
        }
    });
    
    // Auto Resize
    const resizeObserver = new ResizeObserver(entries => {
        if (entries.length === 0 || entries[0].target !== chartDiv) return;
        const newRect = entries[0].contentRect;
        chart.applyOptions({ width: newRect.width, height: newRect.height });
    });
    resizeObserver.observe(chartDiv);
    
    return { chart, series: candlestickSeries, volSeries: volumeSeries, ema50: ema50Series, ema200: ema200Series, domElement: card };
}

async function renderCharts(tradesObj) {
    let symbolsToRender = [];
    const tradesList = Object.values(tradesObj);
    
    if (tradesList.length === 0) {
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
    grid.innerHTML = '';
    
    for (const item of symbolsToRender) {
        const { chart, series, volSeries, ema50, ema200, domElement } = createChartContainer(item.symbol, item.direction);
        
        try {
            const rawKlines = await fetchBinanceKlines(item.symbol);
            if (!rawKlines || rawKlines.length === 0) {
                console.error("No data for", item.symbol);
                continue;
            }
            
            const candleData = rawKlines.map(d => ({ time: Math.floor(d.time), open: d.open, high: d.high, low: d.low, close: d.close }));
            const volData = rawKlines.map(d => ({ time: Math.floor(d.time), value: d.value, color: d.color }));
            const ema50Data = calculateEMA(rawKlines, 50).map(d => ({ time: Math.floor(d.time), value: d.value }));
            const ema200Data = calculateEMA(rawKlines, 200).map(d => ({ time: Math.floor(d.time), value: d.value }));
            
            series.setData(candleData);
            volSeries.setData(volData);
            ema50.setData(ema50Data);
            ema200.setData(ema200Data);
            
            // Draw Trade Overlays
            if (item.trade) {
                const t = item.trade;
                
                if (t.entry_price > 0) {
                    series.createPriceLine({
                        price: t.entry_price,
                        color: '#00ff88',
                        lineWidth: 2,
                        lineStyle: LightweightCharts.LineStyle.Solid,
                        axisLabelVisible: true,
                        title: 'ENTRY',
                    });
                }
                if (t.stop_loss > 0) {
                    series.createPriceLine({
                        price: t.stop_loss,
                        color: '#ff3366',
                        lineWidth: 2,
                        lineStyle: LightweightCharts.LineStyle.Dashed,
                        axisLabelVisible: true,
                        title: 'SL',
                    });
                }
                if (t.target > 0) {
                    series.createPriceLine({
                        price: t.target,
                        color: '#00b8ff',
                        lineWidth: 2,
                        lineStyle: LightweightCharts.LineStyle.Dashed,
                        axisLabelVisible: true,
                        title: 'TP',
                    });
                }
            }
            
            chart.timeScale().fitContent();
        } catch (e) {
            console.error(`Failed to load chart for ${item.symbol}`, e);
        }
    }
}
