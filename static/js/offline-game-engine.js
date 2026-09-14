/**
 * Food Safety Run -- "Inspect. Avoid. Protect."
 *
 * A small original endless-runner, themed around this app's own domain
 * (hygiene inspections, contamination risk, safety grading) rather than a
 * reskin of the Chrome dino game. Pure Canvas 2D + requestAnimationFrame,
 * no dependencies, no network calls once this file has loaded, no DOM
 * elements created per-frame (only the score/HUD text nodes update, via
 * textContent).
 *
 * This file is only fetched when the player actually opens the game (see
 * static/js/offline-network.js's lazy loader) so it never adds weight to
 * normal application pages.
 *
 * Storage: localStorage only (FoodSafetyRun_bestScore,
 * FoodSafetyRun_bestSafety, FoodSafetyRun_soundOn) -- no database tables,
 * no server calls, nothing sensitive.
 */
(function () {
    "use strict";

    if (window.FoodSafetyRun && window.FoodSafetyRun.__engineReady) {
        return;
    }

    // ---- Config -----------------------------------------------------------

    var LOGICAL_W = 800;
    var LOGICAL_H = 450;
    var GROUND_Y = 360;
    var GRAVITY = 0.62;
    var JUMP_VELOCITY = -12.5;
    var BASE_SPEED = 5.2;
    var MAX_SPEED = 12;
    var SPEED_RAMP_PER_SCORE = 0.00045;
    var MILESTONE_SCORE = 5000;
    var SAFETY_MAX = 100;

    var HAZARDS = [
        { key: "bacteria", glyph: "\u{1F9A0}", type: "graze", penalty: 10, w: 30, h: 30 },
        { key: "flies", glyph: "\u{1FAB0}", type: "graze", penalty: 5, w: 26, h: 26, floaty: true },
        { key: "garbage", glyph: "\u{1F5D1}️", type: "solid", w: 36, h: 40 },
        { key: "contaminated", glyph: "⚠️", type: "solid", w: 34, h: 34 },
        { key: "dirtyWater", glyph: "\u{1F6B1}", type: "solid", w: 40, h: 26, low: true },
    ];
    var COLLECTIBLES = [
        { key: "soap", glyph: "\u{1F9FC}", safety: 2, score: 50 },
        { key: "gloves", glyph: "\u{1F9E4}", safety: 2, score: 50 },
        { key: "cleanWater", glyph: "\u{1F4A7}", safety: 3, score: 75 },
        { key: "hygieneBadge", glyph: "✅", safety: 5, score: 150 },
        { key: "star", glyph: "⭐", safety: 1, score: 100 },
    ];

    var GRADE_THRESHOLDS = [
        { min: 95, label: "A+", cls: "grade-Aplus" },
        { min: 85, label: "A", cls: "grade-A" },
        { min: 70, label: "B", cls: "grade-B" },
        { min: 50, label: "C", cls: "grade-C" },
        { min: 0, label: "D", cls: "grade-D" },
    ];

    var STORAGE_BEST_SCORE = "FoodSafetyRun_bestScore";
    var STORAGE_BEST_SAFETY = "FoodSafetyRun_bestSafetyScore";
    var STORAGE_SOUND = "FoodSafetyRun_soundOn";

    function readStorage(key, fallback) {
        try {
            var v = window.localStorage.getItem(key);
            return v === null ? fallback : v;
        } catch (e) {
            return fallback;
        }
    }
    function writeStorage(key, value) {
        try { window.localStorage.setItem(key, value); } catch (e) {}
    }

    function gradeFor(safety) {
        for (var i = 0; i < GRADE_THRESHOLDS.length; i++) {
            if (safety >= GRADE_THRESHOLDS[i].min) return GRADE_THRESHOLDS[i];
        }
        return GRADE_THRESHOLDS[GRADE_THRESHOLDS.length - 1];
    }

    var prefersReducedMotion = window.matchMedia &&
        window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    // ---- Sound (WebAudio synthesized beeps -- no audio files, no network) --

    var AudioCtx = window.AudioContext || window.webkitAudioContext;
    var audioCtx = null;
    var soundOn = readStorage(STORAGE_SOUND, "1") === "1";

    function tone(freq, durationMs, type) {
        if (!soundOn || !AudioCtx) return;
        try {
            if (!audioCtx) audioCtx = new AudioCtx();
            if (audioCtx.state === "suspended") audioCtx.resume();
            var osc = audioCtx.createOscillator();
            var gain = audioCtx.createGain();
            osc.type = type || "sine";
            osc.frequency.value = freq;
            gain.gain.setValueAtTime(0.08, audioCtx.currentTime);
            gain.gain.exponentialRampToValueAtTime(0.0001, audioCtx.currentTime + durationMs / 1000);
            osc.connect(gain).connect(audioCtx.destination);
            osc.start();
            osc.stop(audioCtx.currentTime + durationMs / 1000);
        } catch (e) {}
    }
    var sfx = {
        jump: function () { tone(520, 90, "square"); },
        collect: function () { tone(880, 110, "triangle"); },
        hit: function () { tone(140, 220, "sawtooth"); },
        gameover: function () { tone(110, 420, "sawtooth"); },
        milestone: function () { tone(660, 160, "triangle"); setTimeout(function () { tone(990, 220, "triangle"); }, 140); },
    };

    // ---- DOM construction (built once, lazily, on first open) --------------

    var root = null;
    var els = {};
    var previouslyFocused = null;

    function el(tag, className, html) {
        var e = document.createElement(tag);
        if (className) e.className = className;
        if (html !== undefined) e.innerHTML = html;
        return e;
    }

    function buildDom() {
        if (root) return;
        root = el("div", "fsr-overlay");
        root.setAttribute("role", "dialog");
        root.setAttribute("aria-modal", "true");
        root.setAttribute("aria-label", "Food Safety Run");

        var stage = el("div", "fsr-stage");

        var topbar = el("div", "fsr-topbar");
        topbar.innerHTML =
            '<div class="fsr-brand"><span class="fsr-brand-badge"><i class="fa-solid fa-user-shield" aria-hidden="true"></i></span>Food Safety Run</div>' +
            '<div class="fsr-hud">' +
            '<span>Score <strong data-fsr-score>0</strong></span>' +
            '<span>Best <strong data-fsr-best>0</strong></span>' +
            '<span class="fsr-hud-safety" data-fsr-safety-wrap>Safety <strong data-fsr-safety>100%</strong></span>' +
            "</div>" +
            '<div class="fsr-topbar-actions">' +
            '<button type="button" class="fsr-icon-btn" data-fsr-mute aria-label="Toggle sound"><i class="fa-solid fa-volume-high" aria-hidden="true"></i></button>' +
            '<button type="button" class="fsr-icon-btn" data-fsr-pause aria-label="Pause"><i class="fa-solid fa-pause" aria-hidden="true"></i></button>' +
            '<button type="button" class="fsr-icon-btn" data-fsr-exit aria-label="Exit game"><i class="fa-solid fa-xmark" aria-hidden="true"></i></button>' +
            "</div>";

        var canvasWrap = el("div", "fsr-canvas-wrap");
        var canvas = el("canvas");
        canvas.setAttribute("tabindex", "0");
        canvasWrap.appendChild(canvas);

        var hint = el("div", "fsr-hint", "SPACE / TAP TO JUMP");
        canvasWrap.appendChild(hint);

        var screenIdle = el("div", "fsr-screen is-active");
        screenIdle.innerHTML =
            '<div class="fsr-screen-icon"><i class="fa-solid fa-magnifying-glass" aria-hidden="true"></i></div>' +
            '<h2 class="fsr-screen-title">FOOD SAFETY RUN</h2>' +
            '<p class="fsr-screen-tagline">Inspect. Avoid. Protect.</p>' +
            '<div class="fsr-screen-actions"><button type="button" class="fsr-btn fsr-btn-primary" data-fsr-start>Start Inspection</button></div>';
        canvasWrap.appendChild(screenIdle);

        var screenPaused = el("div", "fsr-screen");
        screenPaused.innerHTML =
            '<div class="fsr-screen-icon"><i class="fa-solid fa-pause" aria-hidden="true"></i></div>' +
            '<h2 class="fsr-screen-title">PAUSED</h2>' +
            '<div class="fsr-screen-actions"><button type="button" class="fsr-btn fsr-btn-primary" data-fsr-resume>Resume</button>' +
            '<button type="button" class="fsr-btn fsr-btn-ghost" data-fsr-exit>Exit Game</button></div>';
        canvasWrap.appendChild(screenPaused);

        var screenOver = el("div", "fsr-screen is-gameover");
        screenOver.innerHTML =
            '<div class="fsr-screen-icon"><i class="fa-solid fa-triangle-exclamation" aria-hidden="true"></i></div>' +
            '<h2 class="fsr-screen-title">INSPECTION FAILED</h2>' +
            '<div class="fsr-grade-badge" data-fsr-grade-badge>D</div>' +
            '<div class="fsr-stat-grid">' +
            '<div class="fsr-stat"><div class="fsr-stat-label">Score</div><div class="fsr-stat-value" data-fsr-final-score>0</div></div>' +
            '<div class="fsr-stat"><div class="fsr-stat-label">Safety Score</div><div class="fsr-stat-value" data-fsr-final-safety>0%</div></div>' +
            '<div class="fsr-stat"><div class="fsr-stat-label">Hazards Avoided</div><div class="fsr-stat-value" data-fsr-avoided>0</div></div>' +
            '<div class="fsr-stat"><div class="fsr-stat-label">Hygiene Items</div><div class="fsr-stat-value" data-fsr-collected>0</div></div>' +
            "</div>" +
            '<div class="fsr-screen-actions"><button type="button" class="fsr-btn fsr-btn-primary" data-fsr-restart>Play Again</button>' +
            '<button type="button" class="fsr-btn fsr-btn-ghost" data-fsr-exit>Return to Portal</button></div>';
        canvasWrap.appendChild(screenOver);

        var screenMilestone = el("div", "fsr-screen is-milestone");
        screenMilestone.innerHTML =
            '<div class="fsr-screen-icon"><i class="fa-solid fa-award" aria-hidden="true"></i></div>' +
            '<h2 class="fsr-screen-title">INSPECTION COMPLETE</h2>' +
            '<div class="fsr-grade-badge" data-fsr-grade-badge-m>A+</div>' +
            '<div class="fsr-stat-grid">' +
            '<div class="fsr-stat"><div class="fsr-stat-label">Score</div><div class="fsr-stat-value" data-fsr-final-score-m>0</div></div>' +
            '<div class="fsr-stat"><div class="fsr-stat-label">Safety Score</div><div class="fsr-stat-value" data-fsr-final-safety-m>0%</div></div>' +
            "</div>" +
            '<div class="fsr-screen-actions"><button type="button" class="fsr-btn fsr-btn-primary" data-fsr-restart>Play Again</button>' +
            '<button type="button" class="fsr-btn fsr-btn-ghost" data-fsr-exit>Return to Portal</button></div>';
        canvasWrap.appendChild(screenMilestone);

        canvasWrap.appendChild(hint);
        stage.appendChild(topbar);
        stage.appendChild(canvasWrap);
        var footer = el("div", "fsr-footer-note", "Runs fully offline &middot; nothing here is sent to a server");
        stage.appendChild(footer);
        root.appendChild(stage);
        document.body.appendChild(root);

        els = {
            root: root,
            canvas: canvas,
            canvasWrap: canvasWrap,
            hint: hint,
            score: topbar.querySelector("[data-fsr-score]"),
            best: topbar.querySelector("[data-fsr-best]"),
            safety: topbar.querySelector("[data-fsr-safety]"),
            safetyWrap: topbar.querySelector("[data-fsr-safety-wrap]"),
            muteBtn: topbar.querySelector("[data-fsr-mute]"),
            pauseBtn: topbar.querySelector("[data-fsr-pause]"),
            screenIdle: screenIdle,
            screenPaused: screenPaused,
            screenOver: screenOver,
            screenMilestone: screenMilestone,
            finalScore: screenOver.querySelector("[data-fsr-final-score]"),
            finalSafety: screenOver.querySelector("[data-fsr-final-safety]"),
            avoided: screenOver.querySelector("[data-fsr-avoided]"),
            collected: screenOver.querySelector("[data-fsr-collected]"),
            gradeBadge: screenOver.querySelector("[data-fsr-grade-badge]"),
            finalScoreM: screenMilestone.querySelector("[data-fsr-final-score-m]"),
            finalSafetyM: screenMilestone.querySelector("[data-fsr-final-safety-m]"),
            gradeBadgeM: screenMilestone.querySelector("[data-fsr-grade-badge-m]"),
        };

        wireControls();
        updateMuteIcon();
    }

    // ---- Game state ---------------------------------------------------------

    var ctx = null;
    var dpr = 1;
    var rafId = null;
    var lastTs = 0;
    var gameState = "idle"; // idle | running | paused | gameover | milestone
    var player, obstacles, collectibles, spawnTimer, speed, distance, score, safety;
    var hazardsAvoided, itemsCollected, particles;
    var bgOffset = 0;

    function resetRun() {
        player = { x: 90, y: GROUND_Y, vy: 0, w: 34, h: 40, onGround: true };
        obstacles = [];
        collectibles = [];
        spawnTimer = 0;
        speed = BASE_SPEED;
        distance = 0;
        score = 0;
        safety = SAFETY_MAX;
        hazardsAvoided = 0;
        itemsCollected = 0;
        particles = [];
    }

    function resizeCanvas() {
        if (!els.canvas) return;
        var rect = els.canvasWrap.getBoundingClientRect();
        dpr = Math.min(window.devicePixelRatio || 1, 2);
        els.canvas.width = Math.round(rect.width * dpr);
        els.canvas.height = Math.round(rect.height * dpr);
        ctx = els.canvas.getContext("2d");
        ctx.setTransform(dpr * (rect.width / LOGICAL_W), 0, 0, dpr * (rect.width / LOGICAL_W), 0, 0);
    }

    function showScreen(name) {
        [els.screenIdle, els.screenPaused, els.screenOver, els.screenMilestone].forEach(function (s) {
            s.classList.remove("is-active");
        });
        var map = { idle: els.screenIdle, paused: els.screenPaused, gameover: els.screenOver, milestone: els.screenMilestone };
        var active = map[name];
        if (active) active.classList.add("is-active");
        els.hint.style.opacity = (name === "idle") ? "1" : "0";

        // Keyboard/screen-reader users landing on a new screen should not
        // have to hunt for it -- move focus to its primary action. Gameplay
        // itself focuses the canvas so Space/Arrow keys work immediately.
        if (active) {
            var primary = active.querySelector(".fsr-btn-primary");
            if (primary) primary.focus();
        } else if (name === "running" && els.canvas) {
            els.canvas.focus();
        }
    }

    function updateHud() {
        els.score.textContent = Math.floor(score);
        els.best.textContent = Math.floor(parseInt(readStorage(STORAGE_BEST_SCORE, "0"), 10) || 0);
        els.safety.textContent = Math.round(safety) + "%";
        els.safetyWrap.classList.toggle("is-low", safety <= 30);
        els.safetyWrap.classList.toggle("is-mid", safety > 30 && safety <= 60);
    }

    function jump() {
        if (gameState === "idle") { start(); return; }
        if (gameState !== "running") return;
        if (player.onGround) {
            player.vy = JUMP_VELOCITY;
            player.onGround = false;
            sfx.jump();
        }
    }

    function start() {
        resetRun();
        gameState = "running";
        showScreen("running");
        updateHud();
        lastTs = 0;
        if (!rafId) rafId = requestAnimationFrame(loop);
    }

    function pause() {
        if (gameState !== "running") return;
        gameState = "paused";
        showScreen("paused");
    }
    function resume() {
        if (gameState !== "paused") return;
        gameState = "running";
        showScreen("running");
        lastTs = 0;
        if (!rafId) rafId = requestAnimationFrame(loop);
    }

    function endRun(reason) {
        gameState = "gameover";
        var best = parseInt(readStorage(STORAGE_BEST_SCORE, "0"), 10) || 0;
        var bestSafety = parseInt(readStorage(STORAGE_BEST_SAFETY, "0"), 10) || 0;
        if (Math.floor(score) > best) writeStorage(STORAGE_BEST_SCORE, Math.floor(score));
        if (Math.floor(safety) > bestSafety) writeStorage(STORAGE_BEST_SAFETY, Math.floor(safety));

        var g = gradeFor(safety);
        els.finalScore.textContent = Math.floor(score);
        els.finalSafety.textContent = Math.round(safety) + "%";
        els.avoided.textContent = hazardsAvoided;
        els.collected.textContent = itemsCollected;
        els.gradeBadge.textContent = g.label;
        els.gradeBadge.className = "fsr-grade-badge " + g.cls;
        updateHud();
        sfx.gameover();
        showScreen("gameover");
    }

    function completeMilestone() {
        gameState = "milestone";
        var best = parseInt(readStorage(STORAGE_BEST_SCORE, "0"), 10) || 0;
        var bestSafety = parseInt(readStorage(STORAGE_BEST_SAFETY, "0"), 10) || 0;
        if (Math.floor(score) > best) writeStorage(STORAGE_BEST_SCORE, Math.floor(score));
        if (Math.floor(safety) > bestSafety) writeStorage(STORAGE_BEST_SAFETY, Math.floor(safety));
        var g = gradeFor(safety);
        els.finalScoreM.textContent = Math.floor(score);
        els.finalSafetyM.textContent = Math.round(safety) + "%";
        els.gradeBadgeM.textContent = g.label;
        els.gradeBadgeM.className = "fsr-grade-badge " + g.cls;
        updateHud();
        sfx.milestone();
        showScreen("milestone");
    }

    function spawn() {
        var laneIsCollectible = Math.random() < 0.42;
        if (laneIsCollectible) {
            var c = COLLECTIBLES[Math.floor(Math.random() * COLLECTIBLES.length)];
            var floating = Math.random() < 0.55;
            collectibles.push({
                def: c,
                x: LOGICAL_W + 20,
                y: floating ? GROUND_Y - 90 - Math.random() * 40 : GROUND_Y - 6,
                w: 26, h: 26,
                collected: false,
            });
        } else {
            var h = HAZARDS[Math.floor(Math.random() * HAZARDS.length)];
            var y = h.low ? GROUND_Y - h.h + 10 : (h.floaty ? GROUND_Y - 70 - Math.random() * 30 : GROUND_Y - h.h + 8);
            obstacles.push({
                def: h,
                x: LOGICAL_W + 20,
                y: y,
                w: h.w, h: h.h,
                resolved: false,
            });
        }
    }

    function aabb(a, b) {
        return a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y;
    }

    // Emoji glyphs render with visual padding inside their box, so a
    // full-size hitbox feels unfair ("that didn't even touch me"). Insetting
    // by a forgiving margin makes collisions match what the player actually
    // sees, and collectibles get a slightly generous box so grabbing them
    // feels satisfying rather than pixel-perfect.
    function inset(box, marginRatio) {
        var mx = box.w * marginRatio;
        var my = box.h * marginRatio;
        return { x: box.x + mx, y: box.y + my, w: box.w - mx * 2, h: box.h - my * 2 };
    }

    function step(dt) {
        var speedFactor = dt / 16.6667;
        speed = Math.min(MAX_SPEED, BASE_SPEED + score * SPEED_RAMP_PER_SCORE);
        distance += speed * speedFactor;
        score += speed * 0.12 * speedFactor;
        if (!prefersReducedMotion) bgOffset -= speed * 0.5 * speedFactor;

        player.vy += GRAVITY * speedFactor;
        player.y += player.vy * speedFactor;
        if (player.y >= GROUND_Y) {
            player.y = GROUND_Y;
            player.vy = 0;
            player.onGround = true;
        }

        spawnTimer -= speedFactor;
        if (spawnTimer <= 0) {
            spawn();
            var gap = Math.max(38, 78 - speed * 3.2);
            spawnTimer = gap + Math.random() * 30;
        }

        var playerBox = inset({ x: player.x, y: player.y - player.h, w: player.w, h: player.h }, 0.16);

        for (var i = obstacles.length - 1; i >= 0; i--) {
            var o = obstacles[i];
            o.x -= speed * speedFactor;
            var box = inset({ x: o.x, y: o.y - o.h, w: o.w, h: o.h }, 0.2);
            if (!o.resolved && aabb(playerBox, box)) {
                o.resolved = true;
                if (o.def.type === "solid") {
                    endRun("collision");
                    return;
                }
                safety = Math.max(0, safety - o.def.penalty);
                sfx.hit();
                updateHud();
                if (safety <= 0) {
                    endRun("safety-zero");
                    return;
                }
            }
            if (!o.resolved && o.x + o.w < player.x) {
                o.resolved = true;
                hazardsAvoided += 1;
            }
            if (o.x + o.w < -20) obstacles.splice(i, 1);
        }

        for (var j = collectibles.length - 1; j >= 0; j--) {
            var c = collectibles[j];
            c.x -= speed * speedFactor;
            var cbox = inset({ x: c.x, y: c.y - c.h, w: c.w, h: c.h }, -0.12);
            if (!c.collected && aabb(playerBox, cbox)) {
                c.collected = true;
                itemsCollected += 1;
                safety = Math.min(SAFETY_MAX, safety + c.def.safety);
                score += c.def.score;
                sfx.collect();
                updateHud();
            }
            if (c.x + c.w < -20 || c.collected) collectibles.splice(j, 1);
        }

        updateHud();
        if (score >= MILESTONE_SCORE) {
            completeMilestone();
        }
    }

    function drawBackground() {
        ctx.clearRect(0, 0, LOGICAL_W, LOGICAL_H);
        var sky = ctx.createLinearGradient(0, 0, 0, GROUND_Y);
        sky.addColorStop(0, "#eaf6f3");
        sky.addColorStop(1, "#cfe9ea");
        ctx.fillStyle = sky;
        ctx.fillRect(0, 0, LOGICAL_W, GROUND_Y + 40);

        // distant stall silhouettes (parallax)
        ctx.fillStyle = "rgba(6, 78, 59, 0.12)";
        var spacing = 180;
        var offset = ((bgOffset * 0.4) % spacing + spacing) % spacing;
        for (var i = -1; i < LOGICAL_W / spacing + 1; i++) {
            var bx = i * spacing - offset;
            ctx.fillRect(bx, GROUND_Y - 70, 70, 70);
            ctx.fillRect(bx + 14, GROUND_Y - 92, 42, 22);
        }

        ctx.fillStyle = "#059669";
        ctx.fillRect(0, GROUND_Y, LOGICAL_W, LOGICAL_H - GROUND_Y);
        ctx.fillStyle = "rgba(255,255,255,0.5)";
        var dashSpacing = 46;
        var dashOffset = ((bgOffset) % dashSpacing + dashSpacing) % dashSpacing;
        for (var d = -1; d < LOGICAL_W / dashSpacing + 1; d++) {
            ctx.fillRect(d * dashSpacing - dashOffset, GROUND_Y + 16, 24, 4);
        }
    }

    function drawEmoji(glyph, cx, cy, size) {
        ctx.font = size + "px 'Apple Color Emoji','Segoe UI Emoji','Noto Color Emoji',sans-serif";
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText(glyph, cx, cy);
    }

    function drawPlayer() {
        var bob = player.onGround && gameState === "running" && !prefersReducedMotion
            ? Math.sin(distance * 0.25) * 2 : 0;
        drawEmoji("\u{1F9D1}‍⚕️", player.x + player.w / 2, player.y - player.h / 2 + bob, 36);
    }

    function draw() {
        drawBackground();
        obstacles.forEach(function (o) {
            drawEmoji(o.def.glyph, o.x + o.w / 2, o.y - o.h / 2, Math.max(o.w, o.h));
        });
        collectibles.forEach(function (c) {
            drawEmoji(c.def.glyph, c.x + c.w / 2, c.y - c.h / 2, 24);
        });
        drawPlayer();
    }

    function loop(ts) {
        if (gameState !== "running") { rafId = null; return; }
        if (!lastTs) lastTs = ts;
        var dt = Math.min(48, ts - lastTs);
        lastTs = ts;
        step(dt);
        if (gameState === "running") {
            draw();
            rafId = requestAnimationFrame(loop);
        } else {
            rafId = null;
        }
    }

    // ---- Controls -----------------------------------------------------------

    function wireControls() {
        window.addEventListener("resize", resizeCanvas);
        window.addEventListener("orientationchange", resizeCanvas);

        // The lazy-loaded stylesheet's <link> isn't awaited before this
        // engine runs (only the script is), so the very first resizeCanvas()
        // call can land before offline-game.css has applied its
        // aspect-ratio -- ResizeObserver catches that (and sidebar
        // collapse/orientation changes) instead of a one-shot calculation.
        if ("ResizeObserver" in window) {
            new ResizeObserver(function () { resizeCanvas(); }).observe(els.canvasWrap);
        }

        els.canvas.addEventListener("pointerdown", function (e) {
            e.preventDefault();
            jump();
        });
        els.screenIdle.querySelector("[data-fsr-start]").addEventListener("click", start);
        els.screenOver.querySelectorAll("[data-fsr-restart]").forEach(function (b) { b.addEventListener("click", start); });
        els.screenMilestone.querySelectorAll("[data-fsr-restart]").forEach(function (b) { b.addEventListener("click", start); });
        root.querySelectorAll("[data-fsr-exit]").forEach(function (b) { b.addEventListener("click", close); });
        els.screenPaused.querySelector("[data-fsr-resume]").addEventListener("click", resume);
        els.pauseBtn.addEventListener("click", function () {
            if (gameState === "running") pause(); else if (gameState === "paused") resume();
        });
        els.muteBtn.addEventListener("click", function () {
            soundOn = !soundOn;
            writeStorage(STORAGE_SOUND, soundOn ? "1" : "0");
            updateMuteIcon();
        });

        document.addEventListener("keydown", onKeyDown);
    }

    function updateMuteIcon() {
        if (!els.muteBtn) return;
        els.muteBtn.innerHTML = soundOn
            ? '<i class="fa-solid fa-volume-high" aria-hidden="true"></i>'
            : '<i class="fa-solid fa-volume-xmark" aria-hidden="true"></i>';
        els.muteBtn.setAttribute("aria-label", soundOn ? "Mute sound" : "Unmute sound");
    }

    function onKeyDown(e) {
        if (!root || !root.classList.contains("is-open")) return;
        if (e.code === "Space" || e.code === "ArrowUp") {
            e.preventDefault();
            jump();
        } else if (e.key === "Escape") {
            e.preventDefault();
            if (gameState === "running") pause();
            else if (gameState === "paused") resume();
            else close();
        } else if ((e.key === "p" || e.key === "P") && gameState === "running") {
            pause();
        } else if (e.key === "Tab") {
            trapFocus(e);
        }
    }

    // Small, self-contained focus trap: the overlay is a very short-lived
    // modal with only a handful of interactive elements (topbar icons + the
    // current screen's buttons), so a full library isn't warranted -- Tab
    // just wraps within whatever is currently visible instead of escaping
    // to the page underneath.
    function trapFocus(e) {
        var focusable = root.querySelectorAll(
            'button:not([disabled]), [href], canvas[tabindex]'
        );
        var visible = Array.prototype.filter.call(focusable, function (el) {
            return el.offsetParent !== null;
        });
        if (!visible.length) return;
        var first = visible[0];
        var last = visible[visible.length - 1];
        if (e.shiftKey && document.activeElement === first) {
            e.preventDefault();
            last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
            e.preventDefault();
            first.focus();
        }
    }

    // ---- Public API -----------------------------------------------------------

    function open(reason) {
        buildDom();
        previouslyFocused = document.activeElement;
        // The canvas can only be measured once the overlay is actually
        // visible (it's display:none until "is-open" is added) -- resizing
        // before that reads a zero-size box. The ResizeObserver in
        // wireControls() is a further safety net for later size changes
        // (orientation, sidebar collapse), but this call must come after
        // the class flip, not before it.
        root.classList.add("is-open");
        resizeCanvas();
        document.body.classList.add("fsr-lock-scroll");
        gameState = "idle";
        resetRun();
        showScreen("idle");
        updateHud();
        document.dispatchEvent(new CustomEvent("fsr:game-open", { detail: { reason: reason || "manual" } }));
    }

    function close() {
        if (!root) return;
        gameState = "idle";
        if (rafId) { cancelAnimationFrame(rafId); rafId = null; }
        root.classList.remove("is-open");
        document.body.classList.remove("fsr-lock-scroll");
        if (previouslyFocused && typeof previouslyFocused.focus === "function") {
            try { previouslyFocused.focus(); } catch (e) {}
        }
        document.dispatchEvent(new CustomEvent("fsr:game-close"));
    }

    window.FoodSafetyRun = {
        __engineReady: true,
        open: open,
        close: close,
        isOpen: function () { return !!root && root.classList.contains("is-open"); },
    };
})();
