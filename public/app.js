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
