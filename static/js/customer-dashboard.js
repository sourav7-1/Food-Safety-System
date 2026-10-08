/**
 * DIU FoodSafe — Student Portal Dashboard JavaScript
 * Interactive Campus Safety Calendar (AJAX + Bootstrap Popovers)
 * Risk Distribution Doughnut Chart (Chart.js)
 */

document.addEventListener("DOMContentLoaded", function () {
    initCampusCalendar();
    initRiskDistributionChart();
});

/* ==========================================================================
   1. Campus Safety Calendar
   ========================================================================== */
function initCampusCalendar() {
    const calendarContainer = document.getElementById("campusCalendarGrid");
    const calendarMonthLabel = document.getElementById("calendarMonthTitle");
    const prevBtn = document.getElementById("calPrevMonthBtn");
    const nextBtn = document.getElementById("calNextMonthBtn");
    const todayBtn = document.getElementById("calTodayBtn");
    const loadingIndicator = document.getElementById("calendarLoading");

    if (!calendarContainer) return;

    let activePopovers = [];
    const currentDate = new Date();
    let currentYear = currentDate.getFullYear();
    let currentMonth = currentDate.getMonth() + 1; // 1-12

    function disposePopovers() {
        activePopovers.forEach((p) => {
            try {
                p.dispose();
            } catch (e) {
                // ignore
            }
        });
        activePopovers = [];
    }

    async function loadCalendar(year, month) {
        disposePopovers();
        if (loadingIndicator) loadingIndicator.classList.remove("d-none");

        const monthStr = `${year}-${String(month).padStart(2, "0")}`;
        const apiUrl = `/api/customer/calendar?month=${monthStr}`;

        try {
            const response = await fetch(apiUrl, {
                headers: {
                    "X-Requested-With": "XMLHttpRequest",
                    Accept: "application/json",
                },
            });

            if (!response.ok) {
                throw new Error(`HTTP error ${response.status}`);
            }

            const data = await response.json();
            if (data.success) {
                renderCalendar(data);
            }
        } catch (err) {
            console.error("Failed to load campus calendar:", err);
            calendarContainer.innerHTML = `
                <div class="std-empty-state col-12 py-3">
                    <p class="text-danger small mb-0"><i class="fa-solid fa-triangle-exclamation me-1"></i> Unable to load calendar audits.</p>
                </div>
            `;
        } finally {
            if (loadingIndicator) loadingIndicator.classList.add("d-none");
        }
    }

    function renderCalendar(data) {
        if (calendarMonthLabel) {
            calendarMonthLabel.textContent = data.month_name;
        }

        const year = data.year;
        const monthNum = data.month_num;
        const daysInMonth = new Date(year, monthNum, 0).getDate();
        const firstDayIndex = new Date(year, monthNum - 1, 1).getDay(); // 0 = Sun, 1 = Mon...
        const todayStr = data.today;
        const daysMap = data.days || {};

        let html = "";

        // Day of week headers
        const dayNames = ["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"];
        dayNames.forEach((d) => {
            html += `<div class="text-muted fw-bold small pb-1" style="font-size: 11px; text-align: center;">${d}</div>`;
        });

        // Blank days before first day of month
        for (let i = 0; i < firstDayIndex; i++) {
            html += `<div class="std-cal-cell is-empty"></div>`;
        }

        // Days of the month
        for (let day = 1; day <= daysInMonth; day++) {
            const dateStr = `${year}-${String(monthNum).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
            const isToday = dateStr === todayStr;
            const dayData = daysMap[dateStr];

            let dotHtml = "";
            let popoverAttrs = "";
            let extraClasses = "";

            if (isToday) {
                extraClasses += " is-today";
            }

            if (dayData && dayData.count > 0) {
                const highestRisk = dayData.highest_risk || "low";
                let dotClass = "cal-dot-low";
                if (highestRisk === "high") dotClass = "cal-dot-high";
                else if (highestRisk === "medium") dotClass = "cal-dot-medium";

                dotHtml = `<span class="cal-dot ${dotClass}"></span>`;
                extraClasses += " has-audits";

                // Build popover content
                let itemsHtml = dayData.inspections
                    .map((ins) => {
                        let gradeBadge = "#10b981";
                        if (ins.grade === "C" || ins.grade === "D") gradeBadge = "#f59e0b";
                        if (ins.grade === "F") gradeBadge = "#ef4444";

                        const scoreDisplay = ins.score !== null ? `${ins.score}%` : "Audited";
                        return `
                        <div class="cal-popover-item">
                            <div>
                                <div class="fw-bold text-dark text-truncate" style="max-width: 140px;">${escapeHtml(ins.stall_name)}</div>
                                <span class="text-muted" style="font-size: 10px;">${ins.time}</span>
                            </div>
                            <span class="badge rounded-pill" style="background-color: ${gradeBadge}; font-size: 10.5px;">Grade ${ins.grade} (${scoreDisplay})</span>
                        </div>
                    `;
                    })
                    .join("");

                const titleHtml = `<i class='fa-regular fa-calendar-check me-1 text-warning'></i> Audits on ${dateStr}`;
                popoverAttrs = `data-bs-toggle="popover" data-bs-trigger="click" data-bs-html="true" data-bs-custom-class="cal-popover" data-bs-title="${escapeHtml(titleHtml)}" data-bs-content="${escapeHtml(itemsHtml)}"`;
            }

            html += `
                <div class="std-cal-cell${extraClasses}" ${popoverAttrs} tabindex="0" title="${dateStr}">
                    <span>${day}</span>
                    ${dotHtml}
                </div>
            `;
        }

        calendarContainer.innerHTML = html;

        // Initialize Bootstrap Popovers
        const popoverTriggerList = calendarContainer.querySelectorAll('[data-bs-toggle="popover"]');
        popoverTriggerList.forEach((el) => {
            const popoverInstance = new bootstrap.Popover(el, {
                container: "body",
                html: true,
                sanitize: false,
            });
            activePopovers.push(popoverInstance);

            // Close other popovers when one is clicked
            el.addEventListener("click", function (e) {
                e.stopPropagation();
                activePopovers.forEach((p) => {
                    if (p !== popoverInstance) p.hide();
                });
            });
        });
    }

    // Dismiss popovers on outside click
    document.addEventListener("click", function (e) {
        if (!e.target.closest(".popover") && !e.target.closest(".std-cal-cell")) {
            disposePopovers();
        }
    });

    // Navigation events
    if (prevBtn) {
        prevBtn.addEventListener("click", function () {
            currentMonth--;
            if (currentMonth < 1) {
                currentMonth = 12;
                currentYear--;
            }
            loadCalendar(currentYear, currentMonth);
        });
    }

    if (nextBtn) {
        nextBtn.addEventListener("click", function () {
            currentMonth++;
            if (currentMonth > 12) {
                currentMonth = 1;
                currentYear++;
            }
            loadCalendar(currentYear, currentMonth);
        });
    }

    if (todayBtn) {
        todayBtn.addEventListener("click", function () {
            const now = new Date();
            currentYear = now.getFullYear();
            currentMonth = now.getMonth() + 1;
            loadCalendar(currentYear, currentMonth);
        });
    }

    // Initial Load
    loadCalendar(currentYear, currentMonth);
}

/* ==========================================================================
   2. Risk Distribution Doughnut Chart (Chart.js)
   ========================================================================== */
function initRiskDistributionChart() {
    const canvas = document.getElementById("studentRiskChart");
    if (!canvas) return;

    if (typeof Chart === "undefined") {
        console.warn("Chart.js is not loaded.");
        return;
    }

    const rawData = canvas.getAttribute("data-risk-counts");
    let riskCounts = { low: 0, medium: 0, high: 0, critical: 0, unrated: 0 };
    if (rawData) {
        try {
            riskCounts = JSON.parse(rawData);
        } catch (e) {
            console.error("Error parsing risk counts data:", e);
        }
    }

    const labels = ["Low Risk (Safest)", "Medium Risk", "High Risk", "Critical Risk", "Unrated"];
    const values = [
        riskCounts.low || 0,
        riskCounts.medium || 0,
        riskCounts.high || 0,
        riskCounts.critical || 0,
        riskCounts.unrated || 0,
    ];
    const totalStalls = values.reduce((a, b) => a + b, 0);

    const bgColors = [
        "#10b981", // Low - Green
        "#f59e0b", // Medium - Amber
        "#ef4444", // High - Red
        "#991b1b", // Critical - Dark Red
        "#94a3b8", // Unrated - Slate Grey
    ];

    const ctx = canvas.getContext("2d");

    // Center text plugin
    const centerTextPlugin = {
        id: "centerText",
        afterDraw(chart) {
            const { ctx, chartArea: { top, bottom, left, right, width, height } } = chart;
            ctx.save();
            ctx.textAlign = "center";
            ctx.textBaseline = "middle";

            const centerX = left + width / 2;
            const centerY = top + height / 2;

            ctx.font = "800 20px 'Plus Jakarta Sans', sans-serif";
            ctx.fillStyle = "#192128";
            ctx.fillText(totalStalls, centerX, centerY - 8);

            ctx.font = "600 11px 'Plus Jakarta Sans', sans-serif";
            ctx.fillStyle = "#64748b";
            ctx.fillText("Active Stalls", centerX, centerY + 12);

            ctx.restore();
        },
    };

    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
        Chart.defaults.animation = false;
    }

    new Chart(ctx, {
        type: "doughnut",
        data: {
            labels: labels,
            datasets: [
                {
                    data: values,
                    backgroundColor: bgColors,
                    borderWidth: 2,
                    borderColor: "#ffffff",
                    hoverOffset: 6,
                },
            ],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            cutout: "72%",
            plugins: {
                legend: {
                    position: "bottom",
                    labels: {
                        boxWidth: 10,
                        boxHeight: 10,
                        usePointStyle: true,
                        pointStyle: "circle",
                        padding: 12,
                        font: {
                            size: 11,
                            family: "'Plus Jakarta Sans', sans-serif",
                            weight: "600",
                        },
                        color: "#475569",
                    },
                },
                tooltip: {
                    backgroundColor: "#181e24",
                    titleFont: { size: 12, weight: "700" },
                    bodyFont: { size: 11 },
                    padding: 10,
                    cornerRadius: 8,
                    callbacks: {
                        label: function (context) {
                            const count = context.raw || 0;
                            const pct = totalStalls > 0 ? Math.round((count / totalStalls) * 100) : 0;
                            return ` ${context.label}: ${count} (${pct}%)`;
                        },
                    },
                },
            },
        },
        plugins: [centerTextPlugin],
    });
}

function escapeHtml(unsafe) {
    if (!unsafe) return "";
    return String(unsafe)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}
