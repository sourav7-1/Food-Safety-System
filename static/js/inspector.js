/* Inspector portal helpers: quick-view modals, client-side list filtering and
   the evidence lightbox. Everything is delegated from `document` so it keeps
   working after templates/base.html swaps #main-content in place (AJAX form
   submits) -- no per-element listeners to re-bind. */
(function () {
    "use strict";

    // ---- Quick-view modal --------------------------------------------------
    // A trigger carries its data as data-ins-<key> attributes; the modal has
    // matching [data-fill="key"], [data-fill-href="href-key"],
    // [data-fill-tone="key"] (pill: text from data-ins-key, colour from
    // data-ins-key-tone) and [data-fill-grade="key"] targets.
    function fillModal(modal, trigger) {
        var get = function (key) { return trigger.getAttribute("data-ins-" + key); };

        modal.querySelectorAll("[data-fill]").forEach(function (el) {
            var value = get(el.getAttribute("data-fill"));
            el.textContent = value ? value : (el.getAttribute("data-empty") || "—");
        });

        modal.querySelectorAll("[data-fill-href]").forEach(function (el) {
            var value = get(el.getAttribute("data-fill-href"));
            if (value) {
                el.setAttribute("href", value);
                el.classList.remove("d-none");
            } else {
                el.classList.add("d-none");
            }
        });

        modal.querySelectorAll("[data-fill-tone]").forEach(function (el) {
            var key = el.getAttribute("data-fill-tone");
            var value = get(key);
            el.className = "ins-pill ins-pill-" + (get(key + "-tone") || "neutral");
            el.textContent = value || "—";
        });

        modal.querySelectorAll("[data-fill-grade]").forEach(function (el) {
            var value = get(el.getAttribute("data-fill-grade"));
            el.className = "ins-grade ins-grade-" + (value ? value.toLowerCase() : "none");
            el.textContent = value || "—";
        });
    }

    // ---- Notifications: mark read when a card is opened ---------------------
    // A trigger with data-ins-read-url + data-ins-unread="1" is an unread
    // notification. Opening it in the quick-view modal counts as reading it:
    // POST in the background, then clear the card's "new" styling and update
    // every unread counter (sidebar badge, bell dot, stat card, filter chip).
    function setUnreadCount(count) {
        document.querySelectorAll("[data-ins-unread-count]").forEach(function (el) {
            el.textContent = count;
            el.classList.toggle("d-none", count === 0);
        });
        document.querySelectorAll("[data-ins-unread-count-stat]").forEach(function (el) {
            el.textContent = count;
        });
        if (count === 0) {
            document.querySelectorAll("[data-ins-bell-dot]").forEach(function (el) { el.remove(); });
        }
    }

    function markReadFromTrigger(trigger) {
        var url = trigger.getAttribute("data-ins-read-url");
        if (!url || trigger.getAttribute("data-ins-unread") !== "1") { return; }
        var tokenInput = document.querySelector('input[name="_csrf_token"]');
        var body = new FormData();
        if (tokenInput) { body.append("_csrf_token", tokenInput.value); }

        fetch(url, {
            method: "POST",
            body: body,
            headers: { Accept: "application/json", "X-Requested-With": "XMLHttpRequest" },
        })
            .then(function (response) { return response.json(); })
            .then(function (data) {
                if (!data || !data.success) { return; }
                trigger.setAttribute("data-ins-unread", "0");
                var card = trigger.closest("[data-ins-item]");
                if (card) {
                    card.classList.remove("is-unread");
                    card.setAttribute(
                        "data-risk",
                        (card.getAttribute("data-risk") || "").replace(/\bunread\b/, "").trim()
                    );
                    card.querySelectorAll("[data-ins-unread-flag], [data-ins-markread]").forEach(function (el) {
                        el.remove();
                    });
                }
                setUnreadCount(data.unread_count);
            })
            .catch(function () { /* stays unread; the next page load shows the truth */ });
    }

    document.addEventListener("click", function (event) {
        var trigger = event.target.closest("[data-ins-modal]");
        if (trigger && window.bootstrap) {
            var modal = document.querySelector(trigger.getAttribute("data-ins-modal"));
            if (modal) {
                event.preventDefault();
                fillModal(modal, trigger);
                bootstrap.Modal.getOrCreateInstance(modal).show();
                markReadFromTrigger(trigger);
            }
            return;
        }

        // Evidence images open full size in a lightbox.
        var image = event.target.closest("img[data-ins-lightbox]");
        if (image && window.bootstrap) {
            var box = document.getElementById("insLightbox");
            if (box) {
                box.querySelector("img").src = image.currentSrc || image.src;
                box.querySelector("img").alt = image.alt || "";
                box.querySelector("[data-lightbox-caption]").textContent = image.alt || "";
                bootstrap.Modal.getOrCreateInstance(box).show();
            }
        }
    });

    // ---- Client-side search + chip filter -----------------------------------
    // A [data-ins-scope] wrapper holds an optional [data-ins-search] input,
    // [data-ins-chip] buttons (data-value matched against each item's
    // data-risk) and [data-ins-item] cards (data-search = lowercase haystack).
    function applyFilter(scope) {
        var searchInput = scope.querySelector("[data-ins-search]");
        var query = searchInput ? searchInput.value.trim().toLowerCase() : "";
        var activeChip = scope.querySelector("[data-ins-chip].active");
        var risk = activeChip ? activeChip.getAttribute("data-value") : "";
        var visible = 0;

        scope.querySelectorAll("[data-ins-item]").forEach(function (item) {
            var matchesText = !query || (item.getAttribute("data-search") || "").indexOf(query) !== -1;
            // data-risk may hold several space-separated flags (e.g.
            // "complaint unread" on a notification card).
            var flags = (item.getAttribute("data-risk") || "").split(" ");
            var matchesRisk = !risk || flags.indexOf(risk) !== -1;
            var show = matchesText && matchesRisk;
            item.classList.toggle("d-none", !show);
            if (show) { visible += 1; }
        });

        var empty = scope.querySelector("[data-ins-noresults]");
        if (empty) {
            empty.classList.toggle("d-none", visible !== 0);
        }
    }

    document.addEventListener("input", function (event) {
        var scope = event.target.closest("[data-ins-scope]");
        if (scope && event.target.matches("[data-ins-search]")) {
            applyFilter(scope);
        }
    });

    document.addEventListener("click", function (event) {
        var chip = event.target.closest("[data-ins-chip]");
        if (!chip) { return; }
        var scope = chip.closest("[data-ins-scope]");
        if (!scope) { return; }
        scope.querySelectorAll("[data-ins-chip]").forEach(function (other) {
            other.classList.toggle("active", other === chip);
        });
        applyFilter(scope);
    });
})();
