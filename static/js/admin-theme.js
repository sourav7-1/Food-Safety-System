/**
 * DIU FoodSafe — Admin Portal Theme Scripts
 * Handles Floating Sidebar, Navbar Actions, Dynamic Calendar Engine & Dashboard Interactions.
 */

(function () {
    "use strict";

    // -------------------------------------------------------------------------
    // 1. Sidebar Collapse & Mobile Drawer
    // -------------------------------------------------------------------------
    function initSidebar() {
        var toggle = document.getElementById("sidebarCollapseToggle");
        if (toggle) {
            toggle.addEventListener("click", function () {
                var isCollapsed = document.documentElement.classList.toggle("sidebar-collapsed");
                try {
                    localStorage.setItem("adminSidebarCollapsed", isCollapsed ? "1" : "0");
                } catch (e) {
                    console.warn("Could not save sidebar state to localStorage:", e);
                }
                updateSidebarTooltips();
            });
        }

        function updateSidebarTooltips() {
            var isCollapsed = document.documentElement.classList.contains("sidebar-collapsed");
            document.querySelectorAll(".sidebar-link, .sidebar-logout button").forEach(function (el) {
                var span = el.querySelector("span");
                if (span) {
                    if (isCollapsed) {
                        el.setAttribute("title", span.textContent.trim());
                    } else {
                        el.removeAttribute("title");
                    }
                }
            });
        }

        updateSidebarTooltips();
    }

    // -------------------------------------------------------------------------
    // 2. Interactive Calendar Engine (/api/admin/calendar?month=YYYY-MM)
    // -------------------------------------------------------------------------
    var CalendarEngine = (function () {
        var currentYear = new Date().getFullYear();
        var currentMonth = new Date().getMonth() + 1; // 1-12
        var cachedMonthData = {};
        var activePopover = null;

        function formatMonthParam(year, month) {
            return year + "-" + (month < 10 ? "0" + month : month);
        }

        function fetchMonthData(year, month, callback) {
            var param = formatMonthParam(year, month);
            if (cachedMonthData[param]) {
                callback(cachedMonthData[param]);
                return;
            }

            var url = "/api/admin/calendar?month=" + encodeURIComponent(param);
            fetch(url, { headers: { "X-Requested-With": "XMLHttpRequest" } })
                .then(function (res) {
                    if (!res.ok) throw new Error("Calendar API error");
                    return res.json();
                })
                .then(function (data) {
                    cachedMonthData[param] = data;
                    callback(data);
                })
                .catch(function (err) {
                    console.error("Failed to load calendar data:", err);
                    callback(null);
                });
        }

        function renderCalendar(data) {
            var gridEl = document.getElementById("adminCalendarGrid");
            var titleEl = document.getElementById("calendarMonthTitle");
            if (!gridEl) return;

            if (titleEl && data) {
                titleEl.textContent = data.month_name;
            }

            // Dispose any active popovers
            if (window.bootstrap && bootstrap.Popover) {
                document.querySelectorAll(".calendar-cell[data-bs-toggle='popover']").forEach(function (cell) {
                    var inst = bootstrap.Popover.getInstance(cell);
                    if (inst) inst.dispose();
                });
            }

            gridEl.innerHTML = "";

            // Days of week header
            var daysOfWeek = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"];
            daysOfWeek.forEach(function (d) {
                var headerCell = document.createElement("div");
                headerCell.className = "calendar-day-header";
                headerCell.textContent = d;
                gridEl.appendChild(headerCell);
            });

            var firstDay = new Date(currentYear, currentMonth - 1, 1).getDay();
            // Convert Sunday (0) to 6, Monday (1) to 0
            var offset = (firstDay === 0 ? 6 : firstDay - 1);
            var daysInMonth = new Date(currentYear, currentMonth, 0).getDate();

            // Empty cells before month starts
            for (var i = 0; i < offset; i++) {
                var emptyCell = document.createElement("div");
                emptyCell.className = "calendar-cell is-empty";
                gridEl.appendChild(emptyCell);
            }

            var todayStr = (data && data.today) ? data.today : new Date().toISOString().split("T")[0];
            var daysMap = (data && data.days) ? data.days : {};

            for (var day = 1; day <= daysInMonth; day++) {
                var dayKey = formatMonthParam(currentYear, currentMonth) + "-" + (day < 10 ? "0" + day : day);
                var dayInfo = daysMap[dayKey];

                var cell = document.createElement("div");
                cell.className = "calendar-cell";
                if (dayKey === todayStr) {
                    cell.classList.add("is-today");
                }

                var numSpan = document.createElement("span");
                numSpan.className = "day-num";
                numSpan.textContent = day;
                cell.appendChild(numSpan);

                if (dayInfo && dayInfo.count > 0) {
                    var dot = document.createElement("span");
                    dot.className = "calendar-risk-dot";
                    if (dayInfo.highest_risk === "high") {
                        dot.classList.add("risk-dot-high");
                    } else if (dayInfo.highest_risk === "medium") {
                        dot.classList.add("risk-dot-medium");
                    } else {
                        dot.classList.add("risk-dot-low");
                    }
                    cell.appendChild(dot);

                    // Setup Popover for Day Inspections
                    var popoverContent = buildPopoverHtml(dayKey, dayInfo);
                    cell.setAttribute("data-bs-toggle", "popover");
                    cell.setAttribute("data-bs-trigger", "click");
                    cell.setAttribute("data-bs-html", "true");
                    cell.setAttribute("data-bs-placement", "top");
                    cell.setAttribute("data-bs-content", popoverContent);
                    cell.setAttribute("title", '<div class="fw-bold text-dark small"><i class="fa-regular fa-calendar-check me-1 text-primary"></i> ' + escapeHtml(dayKey) + ' (' + dayInfo.count + ' Audits)</div>');
                    cell.classList.add("has-events");
                }

                gridEl.appendChild(cell);
            }

            // Initialize bootstrap popovers
            if (window.bootstrap && bootstrap.Popover) {
                var popoverTriggerList = [].slice.call(gridEl.querySelectorAll('[data-bs-toggle="popover"]'));
                popoverTriggerList.map(function (popoverTriggerEl) {
                    return new bootstrap.Popover(popoverTriggerEl, {
                        sanitize: false,
                        boundary: "clippingParents"
                    });
                });
            }
        }

        function buildPopoverHtml(dateStr, dayInfo) {
            var html = '<div class="calendar-popover-content" style="max-width: 260px; font-size: 12px;">';
            dayInfo.inspections.forEach(function (ins) {
                var riskBadge = '<span class="badge ' + (ins.risk_level === "high" || ins.risk_level === "critical" ? "bg-danger" : (ins.risk_level === "medium" ? "bg-warning text-dark" : "bg-primary")) + ' rounded-pill py-0.5 px-1.5" style="font-size: 9px;">' + escapeHtml(ins.risk_level) + '</span>';
                var scoreBadge = ins.score !== null ? '<span class="fw-bold text-dark">' + ins.score + '%</span>' : '<span class="text-muted">—</span>';
                html += '<div class="p-2 mb-1.5 bg-light rounded-3 border" style="cursor:pointer;" onclick="if(window.openEntityDetailModal) window.openEntityDetailModal(\'inspection\', ' + ins.id + ')">' +
                    '<div class="d-flex align-items-center justify-content-between gap-1">' +
                    '<strong class="text-primary text-truncate" style="max-width: 140px;">' + escapeHtml(ins.stall_name) + '</strong>' +
                    riskBadge +
                    '</div>' +
                    '<div class="d-flex align-items-center justify-content-between text-secondary mt-1" style="font-size: 10.5px;">' +
                    '<span><i class="fa-regular fa-clock me-1"></i>' + escapeHtml(ins.time) + '</span>' +
                    scoreBadge +
                    '</div>' +
                    '</div>';
            });
            html += '</div>';
            return html;
        }

        function nextMonth() {
            if (currentMonth === 12) {
                currentMonth = 1;
                currentYear++;
            } else {
                currentMonth++;
            }
            fetchMonthData(currentYear, currentMonth, renderCalendar);
        }

        function prevMonth() {
            if (currentMonth === 1) {
                currentMonth = 12;
                currentYear--;
            } else {
                currentMonth--;
            }
            fetchMonthData(currentYear, currentMonth, renderCalendar);
        }

        function gotoToday() {
            var now = new Date();
            currentYear = now.getFullYear();
            currentMonth = now.getMonth() + 1;
            fetchMonthData(currentYear, currentMonth, renderCalendar);
        }

        function init() {
            var prevBtn = document.getElementById("calendarPrevBtn");
            var nextBtn = document.getElementById("calendarNextBtn");
            var todayBtn = document.getElementById("calendarTodayBtn");

            if (prevBtn) prevBtn.addEventListener("click", prevMonth);
            if (nextBtn) nextBtn.addEventListener("click", nextMonth);
            if (todayBtn) todayBtn.addEventListener("click", gotoToday);

            // Close active popover on outside click
            document.addEventListener("click", function (e) {
                if (!e.target.closest(".calendar-cell") && !e.target.closest(".popover")) {
                    document.querySelectorAll(".calendar-cell[data-bs-toggle='popover']").forEach(function (cell) {
                        var inst = bootstrap.Popover.getInstance(cell);
                        if (inst) inst.hide();
                    });
                }
            });

            // Initial load
            if (document.getElementById("adminCalendarGrid")) {
                fetchMonthData(currentYear, currentMonth, renderCalendar);
            }
        }

        return {
            init: init,
            refresh: function () {
                cachedMonthData = {};
                fetchMonthData(currentYear, currentMonth, renderCalendar);
            }
        };
    })();

    // -------------------------------------------------------------------------
    // 3. Status Filters & Ongoing Inspections Toggle
    // -------------------------------------------------------------------------
    function initDashboardFilters() {
        var filterChips = document.querySelectorAll(".filter-chip[data-status-filter]");
        filterChips.forEach(function (chip) {
            chip.addEventListener("click", function () {
                filterChips.forEach(function (c) { c.classList.remove("active"); });
                chip.classList.add("active");
                var filterVal = chip.getAttribute("data-status-filter");

                // Filter ongoing pastel cards if present
                var ongoingCards = document.querySelectorAll("[data-inspection-stage]");
                ongoingCards.forEach(function (card) {
                    var stage = (card.getAttribute("data-inspection-stage") || "").toLowerCase();
                    if (filterVal === "all") {
                        card.style.display = "";
                    } else if (filterVal === "pending") {
                        card.style.display = (stage.indexOf("approved") === -1 && stage.indexOf("completed") === -1) ? "" : "none";
                    } else if (filterVal === "completed") {
                        card.style.display = (stage.indexOf("approved") !== -1 || stage.indexOf("completed") !== -1) ? "" : "none";
                    }
                });

                // Filter recent inspections table rows if present
                var tableRows = document.querySelectorAll(".admin-table tbody tr[data-row-status]");
                tableRows.forEach(function (row) {
                    var status = (row.getAttribute("data-row-status") || "").toLowerCase();
                    if (filterVal === "all") {
                        row.style.display = "";
                    } else if (filterVal === "pending") {
                        row.style.display = (status.indexOf("approved") === -1 && status.indexOf("completed") === -1) ? "" : "none";
                    } else if (filterVal === "completed") {
                        row.style.display = (status.indexOf("approved") !== -1 || status.indexOf("completed") !== -1) ? "" : "none";
                    }
                });
            });
        });

        // Search trigger button in topbar
        var topbarSearchBtn = document.getElementById("topbarSearchBtn");
        if (topbarSearchBtn) {
            topbarSearchBtn.addEventListener("click", function () {
                var searchInput = document.querySelector("input[name='q'], input[name='search'], .search-bar input");
                if (searchInput) {
                    searchInput.focus();
                    searchInput.scrollIntoView({ behavior: "smooth", block: "center" });
                } else {
                    // Navigate to search / stalls list
                    if (window.AdminAjax && window.AdminAjax.loadAdminPage) {
                        window.AdminAjax.loadAdminPage("/admin/stalls");
                    } else {
                        window.location.href = "/admin/stalls";
                    }
                }
            });
        }
    }

    function escapeHtml(str) {
        if (!str) return "";
        return String(str)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;");
    }

    // Initialize all theme modules on DOMContentLoaded & AJAX content updates
    function initAll() {
        initSidebar();
        CalendarEngine.init();
        initDashboardFilters();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initAll);
    } else {
        initAll();
    }

    document.addEventListener("admin:content-updated", function () {
        initAll();
    });

    window.AdminTheme = {
        init: initAll,
        CalendarEngine: CalendarEngine
    };
})();
