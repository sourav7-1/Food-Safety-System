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

    document.addEventListener("click", function (event) {
        var trigger = event.target.closest("[data-ins-modal]");
        if (trigger && window.bootstrap) {
            var modal = document.querySelector(trigger.getAttribute("data-ins-modal"));
            if (modal) {
                event.preventDefault();
                fillModal(modal, trigger);
                bootstrap.Modal.getOrCreateInstance(modal).show();
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
            var matchesRisk = !risk || item.getAttribute("data-risk") === risk;
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
