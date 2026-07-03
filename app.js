// Constants for SVG calculations
const CIRCUMFERENCE = 251.2; // 2 * pi * r where r=40

// Custom SVG Icons for services
const icons = {
    cursor: `<svg viewBox="0 0 24 24"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-2h2v2zm0-4h-2V7h2v6z"/></svg>`,
    copilot: `<svg viewBox="0 0 24 24"><path d="M12 2A10 10 0 0 0 2 12c0 4.42 2.87 8.17 6.84 9.5.5.08.66-.23.66-.5v-1.69c-2.77.6-3.36-1.34-3.36-1.34-.46-1.16-1.11-1.47-1.11-1.47-.9-.62.07-.6.07-.6 1 .07 1.53 1.03 1.53 1.03.9 1.52 2.34 1.07 2.91.83.09-.65.35-1.09.63-1.34-2.22-.25-4.55-1.11-4.55-4.92 0-1.11.38-2 1.03-2.71-.1-.25-.45-1.29.1-2.64 0 0 .84-.27 2.75 1.02.79-.22 1.65-.33 2.5-.33.85 0 1.71.11 2.5.33 1.91-1.29 2.75-1.02 2.75-1.02.55 1.35.2 2.39.1 2.64.65.71 1.03 1.6 1.03 2.71 0 3.82-2.34 4.66-4.57 4.91.36.31.69.92.69 1.85V21c0 .27.16.59.67.5C19.14 20.16 22 16.42 22 12A10 10 0 0 0 12 2z"/></svg>`,
    codex: `<svg viewBox="0 0 24 24"><path d="M19 3H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm-5 14H7v-2h7v2zm3-4H7v-2h10v2zm0-4H7V7h10v2z"/></svg>`,
    devin: `<svg viewBox="0 0 24 24"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 17h-2v-6h2v6zm0-8h-2V7h2v4z"/></svg>`,
    gemini: `<svg viewBox="0 0 24 24"><path d="M12 2L2 22h20L12 2zm0 4.14L18.42 18H5.58L12 6.14zM11 10h2v4h-2v-4zm0 5h2v2h-2v-2z"/></svg>`,
    claude: `<svg viewBox="0 0 24 24"><path d="M12 2a10 10 0 1 0 10 10A10 10 0 0 0 12 2zm1 14h-2v-2h2zm0-4h-2V7h2z"/></svg>`,
    default: `<svg viewBox="0 0 24 24"><path d="M19 3H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm-2 10h-4v4h-2v-4H7v-2h4V7h2v4h4v2z"/></svg>`
};

document.addEventListener('DOMContentLoaded', () => {
    fetchData();
});

async function fetchData() {
    try {
        const response = await fetch('ai-tracker-sources.json?t=' + new Date().getTime());
        if (!response.ok) {
            throw new Error('Failed to load credit details');
        }
        const data = await response.json();
        renderDashboard(data);
    } catch (error) {
        console.error('Error fetching data:', error);
        document.getElementById('cards-grid').innerHTML = `
            <div class="loading-state">
                <p style="color: var(--color-red);">⚠️ Error loading data. Please ensure ai-tracker-sources.json exists and is valid.</p>
            </div>
        `;
    }
}

function renderDashboard(data) {
    const grid = document.getElementById('cards-grid');
    grid.innerHTML = ''; // Clear loading state
    
    // Set update timestamp
    const lastUpdatedEl = document.getElementById('last-updated');
    const syncStatusText = document.getElementById('sync-status-text');
    
    if (data.lastUpdated) {
        const date = new Date(data.lastUpdated);
        lastUpdatedEl.textContent = `Last updated: ${date.toLocaleString()}`;
        syncStatusText.textContent = 'Sync status: Connected';
    } else {
        lastUpdatedEl.textContent = 'Last updated: Manual / Never';
        syncStatusText.textContent = 'Sync status: Offline';
    }

    let activeTrackersCount = 0;
    let mostUsedSource = { name: 'None', usagePct: 0 };
    let soonestReset = { name: 'N/A', date: null };

    const chartLabels = [];
    const chartUsagePercentages = [];

    data.sources.forEach(source => {
        activeTrackersCount++;
        
        // Find the maximum usage percent among all quotas for this source (for stats & chart)
        let maxUsagePct = 0;
        let mostRestrictiveReset = null;
        let isUnlimited = true;
        let totalQuotasCount = source.quotas ? source.quotas.length : 0;
        
        let quotasHtml = '';
        
        if (source.quotas && source.quotas.length > 0) {
            source.quotas.forEach(q => {
                let used = q.used || 0;
                let limit = q.limit || 0;
                let percent = 0;
                let isQUnlimited = limit === 0;
                
                if (!isQUnlimited) {
                    isUnlimited = false;
                    percent = Math.min(100, Math.round((used / limit) * 100));
                }
                
                if (percent > maxUsagePct) {
                    maxUsagePct = percent;
                }
                
                // Track soonest reset date
                if (q.resetDate) {
                    const resetVal = new Date(q.resetDate);
                    if (!isNaN(resetVal) && (!mostRestrictiveReset || resetVal < mostRestrictiveReset)) {
                        mostRestrictiveReset = resetVal;
                    }
                    if (!isNaN(resetVal) && (!soonestReset.date || resetVal < soonestReset.date)) {
                        soonestReset = { name: `${source.name} (${q.name})`, date: resetVal };
                    }
                }
                
                // Calculate time remaining countdown and bar percentage
                const timeInfo = calculateTimeRemaining(q.resetDate, q.period);
                
                // Determine usage progress bar color
                let progressColor = 'var(--color-green)';
                if (percent > 85) progressColor = 'var(--color-red)';
                else if (percent > 60) progressColor = 'var(--color-yellow)';
                else if (percent > 30) progressColor = 'var(--color-blue)';
                
                if (isQUnlimited) {
                    progressColor = 'var(--color-purple)';
                }
                
                // Format display text (e.g. 79/200 requests or 37%)
                const isPercentBased = (q.period === 'daily' || q.period === 'weekly' || q.period === 'five-hour') && limit === 100;
                const valueText = isPercentBased ? `${percent}% used` : `${used} / ${limit}`;
                
                quotasHtml += `
                    <div class="quota-item">
                        <div class="quota-header">
                            <span class="quota-name">${q.name}</span>
                            <span class="quota-value">${isQUnlimited ? 'Unlimited' : valueText}</span>
                        </div>
                        
                        <!-- Usage bar -->
                        <div class="progress-bar-container">
                            <div class="progress-bar-fill" style="width: ${isQUnlimited ? '100%' : `${percent}%`}; background-color: ${progressColor};"></div>
                        </div>
                        
                        <!-- Time countdown bar -->
                        ${q.resetDate ? `
                        <div class="time-remaining-container">
                            <span class="time-remaining-text">🕒 ${timeInfo.text}</span>
                            <div class="time-bar">
                                <div class="time-bar-fill" style="width: ${timeInfo.pct}%;"></div>
                            </div>
                        </div>
                        ` : ''}
                    </div>
                `;
            });
        } else {
            // Fallback for empty or legacy data
            quotasHtml = `<div class="quota-item" style="color: var(--text-muted);">No active limits configured.</div>`;
        }

        // Keep track of most used source (percentage basis)
        if (!isUnlimited && maxUsagePct > mostUsedSource.usagePct) {
            mostUsedSource = { name: source.name, usagePct: maxUsagePct };
        }

        // Determine icon name
        let iconName = 'default';
        const keywords = source.keywords || [];
        for (const kw of keywords) {
            const cleanKw = kw.toLowerCase();
            if (cleanKw.includes('cursor')) iconName = 'cursor';
            else if (cleanKw.includes('copilot')) iconName = 'copilot';
            else if (cleanKw.includes('codex')) iconName = 'codex';
            else if (cleanKw.includes('devin')) iconName = 'devin';
            else if (cleanKw.includes('gemini')) iconName = 'gemini';
            else if (cleanKw.includes('claude')) iconName = 'claude';
            else if (cleanKw.includes('windsurf')) iconName = 'devin'; // Windsurf share devin/windsurf logo
        }

        // Build HTML card
        const card = document.createElement('div');
        card.className = 'card';
        card.innerHTML = `
            <div class="card-header">
                <div class="card-title-group">
                    <h2>${source.name}</h2>
                    <span class="card-meta">${isUnlimited ? 'Unlimited Plan' : `${totalQuotasCount} active quota${totalQuotasCount > 1 ? 's' : ''}`}</span>
                </div>
                <div class="card-icon">
                    ${icons[iconName] || icons.default}
                </div>
            </div>
            <div class="card-content">
                <div class="quotas-list">
                    ${quotasHtml}
                </div>
            </div>
            <div class="card-footer">
                <div class="note-box">
                    <span>💡</span>
                    <span>${source.notes || 'No description notes.'}</span>
                </div>
            </div>
        `;
        grid.appendChild(card);

        // Prep chart data
        if (!isUnlimited) {
            chartLabels.push(source.name);
            chartUsagePercentages.push(maxUsagePct);
        }
    });

    // Populate overview widgets
    document.getElementById('total-trackers').textContent = activeTrackersCount;
    document.getElementById('most-used-app').textContent = mostUsedSource.name !== 'None' ? `${mostUsedSource.name} (${mostUsedSource.usagePct}%)` : 'All Clear (0%)';
    
    // Calculate simple display for soonest reset text
    if (soonestReset.date) {
        const timeInfo = calculateTimeRemaining(soonestReset.date.toISOString(), null);
        document.getElementById('next-reset').textContent = timeInfo.text.replace(" left", "");
    } else {
        document.getElementById('next-reset').textContent = 'N/A';
    }

    // Render comparison chart
    initChart(chartLabels, chartUsagePercentages);
}

let usageChartInstance = null;
function initChart(labels, data) {
    const ctx = document.getElementById('usageChart').getContext('2d');
    
    if (usageChartInstance) {
        usageChartInstance.destroy();
    }

    usageChartInstance = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [{
                label: 'Usage %',
                data: data,
                backgroundColor: [
                    'rgba(168, 85, 247, 0.45)', // Purple
                    'rgba(59, 130, 246, 0.45)',  // Blue
                    'rgba(16, 185, 129, 0.45)',  // Green
                    'rgba(245, 158, 11, 0.45)',  // Yellow
                    'rgba(239, 68, 68, 0.45)'    // Red
                ],
                borderColor: [
                    'rgba(168, 85, 247, 0.9)',
                    'rgba(59, 130, 246, 0.9)',
                    'rgba(16, 185, 129, 0.9)',
                    'rgba(245, 158, 11, 0.9)',
                    'rgba(239, 68, 68, 0.9)'
                ],
                borderWidth: 1.5,
                borderRadius: 8,
                barThickness: 24
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    display: false
                }
            },
            scales: {
                y: {
                    beginAtZero: true,
                    max: 100,
                    grid: {
                        color: 'rgba(255, 255, 255, 0.05)'
                    },
                    ticks: {
                        color: '#9CA3AF',
                        font: {
                            family: 'Inter',
                            size: 11
                        },
                        callback: function(value) {
                            return value + "%";
                        }
                    }
                },
                x: {
                    grid: {
                        display: false
                    },
                    ticks: {
                        color: '#9CA3AF',
                        font: {
                            family: 'Inter',
                            size: 11
                        }
                    }
                }
            }
        }
    });
}

// Modal handling functions
function openInstructions() {
    document.getElementById('instructions-modal').style.display = 'block';
}

function closeInstructions() {
    document.getElementById('instructions-modal').style.display = 'none';
}

// Close modal if clicked outside
window.onclick = function(event) {
    const modal = document.getElementById('instructions-modal');
    if (event.target === modal) {
        modal.style.display = 'none';
    }
}

// Calculate remaining time countdown and elapsed percentage
function calculateTimeRemaining(resetDateStr, period) {
    if (!resetDateStr) return { text: "No Reset Date", pct: 0 };
    
    const now = new Date();
    const reset = new Date(resetDateStr);
    const diffMs = reset - now;
    
    if (diffMs <= 0) {
        return { text: "Resets now", pct: 100 };
    }
    
    // Calculate time text
    const diffMins = Math.floor(diffMs / 1000 / 60);
    const diffHours = Math.floor(diffMins / 60);
    const diffDays = Math.floor(diffHours / 24);
    
    let text = "";
    if (diffDays > 0) {
        text = `${diffDays}d ${diffHours % 24}h left`;
    } else if (diffHours > 0) {
        text = `${diffHours}h ${diffMins % 60}m left`;
    } else {
        text = `${diffMins}m left`;
    }
    
    // Calculate percentage of time elapsed/remaining in the cycle
    let totalPeriodMs = 1000 * 60 * 60 * 24; // Default 1 day
    const cleanPeriod = (period || "").toLowerCase();
    if (cleanPeriod.includes("weekly") || cleanPeriod.includes("week")) {
        totalPeriodMs = 1000 * 60 * 60 * 24 * 7;
    } else if (cleanPeriod.includes("monthly") || cleanPeriod.includes("month")) {
        totalPeriodMs = 1000 * 60 * 60 * 24 * 30;
    } else if (cleanPeriod.includes("five-hour") || cleanPeriod.includes("5-hour") || cleanPeriod.includes("5 hour")) {
        totalPeriodMs = 1000 * 60 * 60 * 5;
    } else if (cleanPeriod.includes("daily") || cleanPeriod.includes("day")) {
        totalPeriodMs = 1000 * 60 * 60 * 24;
    }
    
    const timeRemainingPct = Math.min(100, Math.max(0, (diffMs / totalPeriodMs) * 100));
    return { text, pct: Math.round(timeRemainingPct) };
}
