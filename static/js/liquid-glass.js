/**
 * DIU FoodSafe — Apple "Liquid Glass" Layer Controller (iOS 26 Style)
 * Handles:
 * 1. Chromium feature-detection for SVG refraction filters in backdrop-filter
 * 2. Pointer-tracking specular highlight updates (--mx, --my) with requestAnimationFrame
 * 3. Dynamic topbar capsule scroll condensation (> 60px)
 * 4. Progressive enhancement for dynamically updated DOM elements
 */
(function () {
    "use strict";

    // 1. Feature Detection: Chromium backdrop-filter refraction support
    function detectLiquidSupport() {
        var isChromium = false;
        try {
            // Check for Chromium brands in userAgentData or window.chrome / Chromium UA signatures
            if (navigator.userAgentData && Array.isArray(navigator.userAgentData.brands)) {
                isChromium = navigator.userAgentData.brands.some(function (b) {
                    return b.brand === "Chromium" || b.brand === "Google Chrome" || b.brand === "Microsoft Edge" || b.brand === "Opera";
                });
            } else if (window.chrome && (window.chrome.webstore || window.chrome.runtime || !window.opr)) {
                isChromium = true;
            } else if (/Chrome|Chromium|Edg|CriOS/i.test(navigator.userAgent) && !/Firefox|FxiOS|Safari/i.test(navigator.userAgent)) {
                isChromium = true;
            } else if (/Chrome/i.test(navigator.userAgent) && !/Firefox/i.test(navigator.userAgent)) {
                isChromium = true;
            }
        } catch (e) {
            isChromium = false;
        }

        // Avoid SVG displacement on mobile screens (<576px) for 60fps GPU performance
        var isSmallScreen = window.innerWidth < 576;

        if (isChromium && !isSmallScreen) {
            document.documentElement.classList.add("supports-liquid");
        } else {
            document.documentElement.classList.remove("supports-liquid");
        }
    }

    // Run feature detection immediately and on resize
    detectLiquidSupport();
    window.addEventListener("resize", detectLiquidSupport, { passive: true });

    // 2. Specular Pointer-Follow Highlight (Throttled with requestAnimationFrame)
    var reduceMotion = false;
    try {
        reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    } catch (e) {}

    var activeTrackingEl = null;
    var mouseX = 0;
    var mouseY = 0;
    var isRafScheduled = false;

    var LIQUID_SELECTOR = ".liquid-glass, .admin-link.active, .sidebar-link.active, .dashboard-link.active, .ins-nav-link.active, .portal-nav-link.active, .sidebar-collapse-toggle, .topbar-icon-btn, .topbar-back-btn, .dashboard-notification-btn, .nav-user-dropdown, .std-action-icon, .round-action-btn, .pastel-grade-pill, .floating-risk-badge, .stall-badge-glass, .topbar-nav-pill-group, .portal-nav-bar, .modal-content";

    function updateSpecularHighlight() {
        isRafScheduled = false;
        if (!activeTrackingEl || reduceMotion) return;

        var rect = activeTrackingEl.getBoundingClientRect();
        if (rect.width <= 0 || rect.height <= 0) return;

        var mx = ((mouseX - rect.left) / rect.width) * 100;
        var my = ((mouseY - rect.top) / rect.height) * 100;

        // Clamp between 0% and 100%
        mx = Math.max(0, Math.min(100, mx));
        my = Math.max(0, Math.min(100, my));

        activeTrackingEl.style.setProperty("--mx", mx.toFixed(1));
        activeTrackingEl.style.setProperty("--my", my.toFixed(1));
    }

    document.addEventListener("pointermove", function (event) {
        if (reduceMotion) return;

        var target = event.target.closest(LIQUID_SELECTOR);
        if (target) {
            activeTrackingEl = target;
            mouseX = event.clientX;
            mouseY = event.clientY;

            if (!isRafScheduled) {
                isRafScheduled = true;
                requestAnimationFrame(updateSpecularHighlight);
            }
        } else if (activeTrackingEl) {
            activeTrackingEl = null;
        }
    }, { passive: true });

    // 3. Dynamic Topbar Scroll Transformation (Condense after 60px)
    var topbars = [];
    function cacheTopbars() {
        topbars = Array.prototype.slice.call(document.querySelectorAll(".admin-topbar, .dashboard-topbar, .site-navbar.sticky-top"));
    }

    var scrollTicking = false;
    function onWindowScroll() {
        if (scrollTicking) return;
        scrollTicking = true;

        requestAnimationFrame(function () {
            var isCondensed = window.scrollY > 60;
            for (var i = 0; i < topbars.length; i++) {
                if (isCondensed) {
                    topbars[i].classList.add("topbar-condensed");
                } else {
                    topbars[i].classList.remove("topbar-condensed");
                }
            }
            scrollTicking = false;
        });
    }

    cacheTopbars();
    window.addEventListener("scroll", onWindowScroll, { passive: true });
    onWindowScroll();

    // Re-bind when dynamic content updates
    function onContentUpdated() {
        cacheTopbars();
        onWindowScroll();
    }

    document.addEventListener("DOMContentLoaded", onContentUpdated);
    document.addEventListener("site:content-updated", onContentUpdated);
    document.addEventListener("admin:content-updated", onContentUpdated);
})();
