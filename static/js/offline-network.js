/**
 * Food Safety Run -- network status + Easter-egg trigger layer.
 *
 * This file is small and loads on every page (included once from
 * templates/base.html and once from templates/admin/base.html, mirroring
 * how other cross-cutting scripts in this app are duplicated between the
 * two independent shells). It is responsible only for:
 *   - knowing ONLINE vs OFFLINE without every page re-implementing
 *     window.addEventListener("offline", ...) itself
 *   - distinguishing "internet unavailable" from "backend unavailable"
 *   - showing a small, non-blocking banner (never a takeover)
 *   - the hidden entry points (Ctrl+Shift+F, 404 link) that lazy-load and
 *     open the actual game engine (static/js/offline-game-engine.js),
 *     which is NOT fetched until the player actually asks to play.
 *
 * No dependency on the game engine file at all -- this module works (and
 * the banner/offline detection remain fully functional) even if the engine
 * script fails to load.
 */
(function () {
    "use strict";

    var GAME_ENGINE_SRC = "/static/js/offline-game-engine.js";
    var GAME_CSS_HREF = "/static/css/offline-game.css";
    var BACKEND_PING_URL = "/";
    var BACKEND_PING_TIMEOUT_MS = 4000;
    var BACKEND_RETRY_INTERVAL_MS = 6000;

    // ---- Network status -------------------------------------------------

    var state = {
        online: navigator.onLine,
        backendReachable: true,
        // "offline" (browser reports no connection) vs "backend" (browser
        // thinks it's online, but our own server didn't answer) vs null
        // when everything is fine.
        reason: null,
    };
    var listeners = [];
    var retryTimer = null;

    function notify() {
        listeners.forEach(function (fn) {
            try { fn(state); } catch (e) {}
        });
        document.dispatchEvent(new CustomEvent("fsr:network-change", { detail: state }));
    }

    function setState(patch) {
        var changed = false;
        Object.keys(patch).forEach(function (key) {
            if (state[key] !== patch[key]) changed = true;
        });
        state = Object.assign({}, state, patch);
        if (changed) notify();
        return changed;
    }

    function pingBackend() {
        if (!navigator.onLine) {
            return Promise.resolve(false);
        }
        var controller = ("AbortController" in window) ? new AbortController() : null;
        var timer = controller
            ? setTimeout(function () { controller.abort(); }, BACKEND_PING_TIMEOUT_MS)
            : null;
        return fetch(BACKEND_PING_URL, {
            method: "HEAD",
            cache: "no-store",
            credentials: "same-origin",
            signal: controller ? controller.signal : undefined,
        })
            .then(function (res) {
                if (timer) clearTimeout(timer);
                return !!res && (res.ok || res.status < 500);
            })
            .catch(function () {
                if (timer) clearTimeout(timer);
                return false;
            });
    }

    function stopRetryLoop() {
        if (retryTimer) {
            clearInterval(retryTimer);
            retryTimer = null;
        }
    }

    function startRetryLoop() {
        stopRetryLoop();
        retryTimer = setInterval(function () {
            recheck();
        }, BACKEND_RETRY_INTERVAL_MS);
    }

    function recheck() {
        if (!navigator.onLine) {
            setState({ online: false, backendReachable: false, reason: "offline" });
            startRetryLoop();
            return;
        }
        pingBackend().then(function (reachable) {
            if (reachable) {
                stopRetryLoop();
                setState({ online: true, backendReachable: true, reason: null });
            } else {
                setState({ online: true, backendReachable: false, reason: "backend" });
                startRetryLoop();
            }
        });
    }

    window.addEventListener("online", recheck);
    window.addEventListener("offline", function () {
        setState({ online: false, backendReachable: false, reason: "offline" });
        startRetryLoop();
    });

    // A failed fetch from the app's own AJAX systems (admin panel nav,
    // portal form submits) is a much faster signal than waiting for a
    // browser-level "offline" event, and it's the only way to notice a
    // reachable-internet-but-dead-backend situation. Those call sites
    // dispatch this event from their existing .catch() blocks instead of
    // duplicating network-probing logic themselves.
    document.addEventListener("fsr:fetch-failed", recheck);

    var FoodSafetyNetwork = {
        getState: function () { return Object.assign({}, state); },
        isOnline: function () { return state.online && state.backendReachable; },
        subscribe: function (fn) {
            listeners.push(fn);
            return function unsubscribe() {
                listeners = listeners.filter(function (l) { return l !== fn; });
            };
        },
        recheck: recheck,
    };
    window.FoodSafetyNetwork = FoodSafetyNetwork;

    // ---- Non-blocking banner ---------------------------------------------
    // Per the product rule this is built against: a brief connectivity blip
    // must never yank the user into anything. This banner only ever adds
    // itself to the DOM, never removes existing page content, and every
    // action in it is a deliberate click.

    var banner = null;
    var bannerDismissedForThisOutage = false;

    function ensureBanner() {
        if (banner) return banner;
        banner = document.createElement("div");
        banner.className = "fsr-net-banner";
        banner.setAttribute("role", "status");
        banner.setAttribute("aria-live", "polite");
        banner.innerHTML =
            '<div class="fsr-net-banner-icon"><i class="fa-solid fa-plug-circle-xmark" aria-hidden="true"></i></div>' +
            '<div class="fsr-net-banner-text">' +
            '<span class="fsr-net-banner-title">Connection lost</span>' +
            '<span class="fsr-net-banner-sub">Food safety never stops.</span>' +
            "</div>" +
            '<div class="fsr-net-banner-actions">' +
            '<button type="button" class="fsr-btn fsr-btn-primary" data-fsr-action="play">Play Food Safety Run</button>' +
            '<button type="button" class="fsr-btn fsr-btn-ghost" data-fsr-action="retry">Retry</button>' +
            "</div>" +
            '<button type="button" class="fsr-net-banner-close" aria-label="Dismiss">&times;</button>';
        document.body.appendChild(banner);

        banner.querySelector('[data-fsr-action="play"]').addEventListener("click", function () {
            openGame("banner");
        });
        banner.querySelector('[data-fsr-action="retry"]').addEventListener("click", function () {
            var btn = banner.querySelector('[data-fsr-action="retry"]');
            btn.disabled = true;
            btn.textContent = "Checking...";
            recheck();
            setTimeout(function () {
                btn.disabled = false;
                btn.textContent = "Retry";
            }, 1200);
        });
        banner.querySelector(".fsr-net-banner-close").addEventListener("click", function () {
            bannerDismissedForThisOutage = true;
            hideBanner();
        });
        return banner;
    }

    function showBanner(backOnline) {
        var el = ensureBanner();
        el.classList.toggle("is-back-online", !!backOnline);
        if (backOnline) {
            el.querySelector(".fsr-net-banner-icon i").className = "fa-solid fa-circle-check";
            el.querySelector(".fsr-net-banner-title").textContent = "Back online";
            el.querySelector(".fsr-net-banner-sub").textContent = "Connection restored.";
            el.querySelector(".fsr-net-banner-actions").style.display = "none";
        } else {
            el.querySelector(".fsr-net-banner-icon i").className = "fa-solid fa-plug-circle-xmark";
            el.querySelector(".fsr-net-banner-title").textContent =
                state.reason === "backend" ? "Server unreachable" : "Connection lost";
            el.querySelector(".fsr-net-banner-sub").textContent =
                state.reason === "backend"
                    ? "You're online, but our server isn't responding."
                    : "Food safety never stops.";
            el.querySelector(".fsr-net-banner-actions").style.display = "";
        }
        el.classList.add("is-visible");
        if (backOnline) {
            setTimeout(hideBanner, 3200);
        }
    }

    function hideBanner() {
        if (banner) banner.classList.remove("is-visible");
    }

    FoodSafetyNetwork.subscribe(function (s) {
        if (!s.online || !s.backendReachable) {
            bannerDismissedForThisOutage = false;
            showBanner(false);
        } else if (!bannerDismissedForThisOutage) {
            showBanner(true);
        }
    });

    // ---- Lazy game loader --------------------------------------------------

    var enginePromise = null;

    function loadEngine() {
        if (window.FoodSafetyRun && window.FoodSafetyRun.__engineReady) {
            return Promise.resolve(window.FoodSafetyRun);
        }
        if (enginePromise) return enginePromise;

        if (!document.querySelector('link[data-fsr-css]')) {
            var link = document.createElement("link");
            link.rel = "stylesheet";
            link.href = GAME_CSS_HREF;
            link.setAttribute("data-fsr-css", "1");
            document.head.appendChild(link);
        }

        enginePromise = new Promise(function (resolve, reject) {
            var script = document.createElement("script");
            script.src = GAME_ENGINE_SRC;
            script.onload = function () { resolve(window.FoodSafetyRun); };
            script.onerror = function () { reject(new Error("Could not load Food Safety Run.")); };
            document.body.appendChild(script);
        });
        return enginePromise;
    }

    function openGame(reason) {
        loadEngine().then(function (game) {
            // Guard against ever calling back into this same placeholder
            // (which would just re-invoke openGame) -- only the real engine
            // sets __engineReady once it has fully initialized.
            if (game && game.__engineReady && typeof game.open === "function") {
                game.open(reason);
            }
        }).catch(function () {
            // Loading the engine itself needs the network -- if that's the
            // one thing that's unreachable, fail quietly rather than throw
            // a console error in front of the user.
        });
    }

    window.FoodSafetyRun = window.FoodSafetyRun || {};
    window.FoodSafetyRun.open = window.FoodSafetyRun.open || openGame;

    // ---- Easter-egg entry points -------------------------------------------

    document.addEventListener("keydown", function (event) {
        if (event.ctrlKey && event.shiftKey && (event.key === "F" || event.key === "f")) {
            event.preventDefault();
            openGame("shortcut");
        }
    });

    document.addEventListener("click", function (event) {
        var trigger = event.target.closest("[data-fsr-open]");
        if (trigger) {
            event.preventDefault();
            openGame(trigger.getAttribute("data-fsr-open") || "link");
        }
    });

    // Initial state on page load (covers a page opened while already
    // offline, not just a mid-session drop).
    if (!navigator.onLine) {
        setState({ online: false, backendReachable: false, reason: "offline" });
    }
})();
