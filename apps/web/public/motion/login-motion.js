// ARES brand motion for the login panel: autoplay, endless loop, no controls or audio.
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const stage = $("stage");
  const canvas = $("world");
  const ctx = canvas.getContext("2d", { alpha: false });
  const scenes = [...document.querySelectorAll(".scene")];
  const names = ["Abertura", "Oportunidades", "Inteligência", "Ação", "Ecossistema", "Próximo passo"];
  const starts = [0, 7, 14, 22, 31, 39];
  const TOTAL = 46;
  const reduceQuery = matchMedia("(prefers-reduced-motion: reduce)");
  let reduced = reduceQuery.matches;
  let playing = !reduced;
  let time = 0, previous = 0, idx = -1, last = 0, rafId = 0;
  const clamp = (v, a = 0, b = 1) => Math.max(a, Math.min(b, v));
  const lerp = (a, b, t) => a + (b - a) * t;
  const ease = (t) => 1 - Math.pow(1 - clamp(t), 4);
  const smooth = (t) => { t = clamp(t); return t * t * (3 - 2 * t); };
  let width = 0, height = 0, compact = false;
  const dpr = Math.min(devicePixelRatio || 1, 2);

  function resize() {
    const r = stage.getBoundingClientRect();
    width = r.width; height = r.height; compact = width <= 480;
    canvas.width = Math.round(width * dpr); canvas.height = Math.round(height * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    if (!playing) render(time);
  }

  const N = 960;
  const points = Array.from({ length: N }, (_, i) => {
    const random = (n) => { const f = Math.sin((i + 1) * n) * 43758.5453; return f - Math.floor(f); };
    return { a: random(12.9898), b: random(78.233), c: random(39.425), r: 0.55 + random(91.11) * 0.9 };
  });
  const gold = [220, 167, 99], silver = [153, 183, 185], warm = [247, 223, 182];
  let geometry = [];
  const coords = (x, y) => [x * width, y * (compact ? width : height)];

  function projection(i, center, radius, rot) {
    const p = points[i], gy = 1 - (2 * (i + 0.5)) / N, r = Math.sqrt(1 - gy * gy), angle = i * 2.399963 + rot;
    const x = Math.cos(angle) * r, z = Math.sin(angle) * r, y = gy, tilt = 0.45;
    const y2 = y * Math.cos(tilt) - z * Math.sin(tilt), z2 = y * Math.sin(tilt) + z * Math.cos(tilt);
    const perspective = 1 / (1.65 - z2 * 0.28);
    return { x: center[0] + x * radius * perspective, y: center[1] + y2 * radius * perspective, z: z2,
      alpha: 0.14 + (z2 + 1) * 0.25, c: i % 11 === 0 ? silver : gold, r: p.r * (1 + (z2 + 1) * 0.3) };
  }

  function form(scene, t, i) {
    const p = points[i];
    switch (scene) {
      case 0: { const center = compact ? coords(0.7, 0.83) : [width * 0.74, height * 0.51]; return projection(i, center, width * (compact ? 0.36 : 0.29), t * 0.14); }
      case 1: { const x = compact ? p.a * width : width * (0.48 + 0.54 * p.a); return { x, y: height * (0.18 + 0.72 * p.b), z: 0, alpha: 0.08 + p.c * 0.15, c: i % 9 === 0 ? gold : silver, r: p.r * 0.6 }; }
      case 2: {
        const center = compact ? coords(0.73, 0.83) : [width * 0.78, height * 0.46];
        const rad = width * (compact ? 0.23 : 0.16);
        if (i < 760) return projection(i, center, rad, t * 0.28);
        const ang = p.b * Math.PI * 2 + t * 0.38, r = rad * (0.85 + p.c * 0.65);
        return { x: center[0] + Math.cos(ang) * r, y: center[1] + Math.sin(ang) * r * 0.32, z: 0, alpha: 0.12 + p.c * 0.4, c: i % 5 === 0 ? warm : gold, r: p.r };
      }
      case 3: { const f = (p.a + t * 0.04) % 1; return { x: width * (0.07 + f * 0.86), y: compact ? width * (0.78 + (p.b - 0.5) * 0.09) : height * (0.565 + (p.b - 0.5) * 0.09), z: 0, alpha: 0.07 + p.c * 0.2, c: gold, r: p.r * 0.7 }; }
      case 4: { const f = (p.a + t * 0.02) % 1; return { x: width * (0.06 + f * 0.88), y: compact ? width * (0.55 + (p.b - 0.5) * 0.065) : height * (0.475 + (p.b - 0.5) * 0.07), z: 0, alpha: 0.06 + p.c * 0.16, c: i % 5 === 0 ? silver : gold, r: p.r * 0.6 }; }
      default: { const center = compact ? coords(0.5, 0.55) : [width * 0.5, height * 0.45]; const q = projection(i, center, width * (compact ? 0.44 : 0.4), -t * 0.09); q.alpha *= 0.55; return q; }
    }
  }

  function draw(scene, local, t) {
    ctx.fillStyle = "#10100f"; ctx.fillRect(0, 0, width, height);
    const core = scene === 2;
    const center = compact ? coords(core ? 0.73 : 0.65, core ? 0.83 : 0.75) : [width * (core ? 0.78 : 0.72), height * 0.48];
    const glow = ctx.createRadialGradient(center[0], center[1], 0, center[0], center[1], width * 0.5);
    glow.addColorStop(0, core ? "#8c603b25" : "#6d54391c"); glow.addColorStop(0.5, "#39352612"); glow.addColorStop(1, "#10100f00");
    ctx.fillStyle = glow; ctx.fillRect(0, 0, width, height);
    ctx.strokeStyle = "#a5977010"; ctx.lineWidth = 0.6;
    const grid = width * 0.055; ctx.beginPath();
    for (let x = 0; x < width; x += grid) { ctx.moveTo(x, 0); ctx.lineTo(x, height); }
    for (let y = 0; y < height; y += grid) { ctx.moveTo(0, y); ctx.lineTo(width, y); }
    ctx.stroke();
    const transition = smooth(local / 0.95);
    const next = [];
    for (let i = 0; i < N; i++) {
      const q = form(scene, t, i), old = geometry[i];
      const mix = old && transition < 1 ? transition : 1;
      next.push(q);
      if (old && mix < 1) {
        q.x = lerp(old.x, q.x, mix); q.y = lerp(old.y, q.y, mix);
        q.alpha = lerp(old.alpha, q.alpha, mix); q.r = lerp(old.r, q.r, mix);
        q.c = q.c.map((n, k) => lerp(old.c[k], n, mix));
      }
      const a = q.alpha * (scene === 0 && t < 2 ? smooth(t / 1.7) : 1);
      ctx.fillStyle = `rgba(${q.c.map(Math.round).join(",")},${a})`;
      ctx.beginPath(); ctx.arc(q.x, q.y, q.r, 0, Math.PI * 2); ctx.fill();
    }
    if (transition >= 1) geometry = next;
    if (scene === 0 || scene === 2 || scene === 5) {
      const c = scene === 2 ? center : compact ? coords(scene === 0 ? 0.7 : 0.5, scene === 0 ? 0.83 : 0.55) : [width * (scene === 0 ? 0.74 : 0.5), height * (scene === 0 ? 0.51 : 0.45)];
      const radius = width * (scene === 2 ? (compact ? 0.185 : 0.115) : scene === 0 ? (compact ? 0.28 : 0.225) : compact ? 0.34 : 0.31);
      for (let k = 0; k < 3; k++) {
        ctx.save(); ctx.translate(...c); ctx.rotate(-0.32 + k * 0.26);
        ctx.strokeStyle = `rgba(220,167,99,${(scene === 5 ? 0.08 : 0.17) * clamp(local)})`; ctx.lineWidth = 0.7;
        ctx.beginPath(); ctx.ellipse(0, 0, radius * (1 + k * 0.06), radius * (0.3 + k * 0.1), 0, 0, Math.PI * 2); ctx.stroke(); ctx.restore();
      }
      if (scene === 2) {
        const f = smooth((local - 1) / 3);
        for (let k = 0; k < 3; k++) {
          const from = compact ? coords(0.4, 0.765 + k * 0.07) : [width * 0.655, height * (0.35 + k * 0.064)], to = c;
          ctx.beginPath(); ctx.moveTo(...from);
          ctx.bezierCurveTo(from[0] + width * 0.05, from[1], to[0] - width * 0.04, to[1], to[0], to[1]);
          ctx.strokeStyle = `rgba(165,190,193,${0.18 * f})`; ctx.stroke();
          const u = (t * 0.55 + k * 0.27) % 1, x = lerp(from[0], to[0], u), y = lerp(from[1], to[1], smooth(u));
          ctx.fillStyle = `rgba(247,223,182,${Math.sin(u * Math.PI) * f * 0.9})`;
          ctx.beginPath(); ctx.arc(x, y, width * 0.0018, 0, Math.PI * 2); ctx.fill();
        }
      }
    }
  }

  function setReveal(el, progress, distance = 20) {
    progress = reduced ? 1 : ease(progress);
    el.style.opacity = progress; el.style.transform = `translate3d(0,${(1 - progress) * distance}px,0)`;
  }

  function setScene(scene, local) {
    const el = scenes[scene], active = scene === idx;
    el.classList.toggle("active", active);
    if (!active) { el.style.opacity = 0; return; }
    el.style.opacity = reduced ? 1 : smooth(local / 0.5); el.style.transform = "none";
    el.querySelectorAll("[data-reveal]").forEach((e) => setReveal(e, (local - Number(e.dataset.reveal)) / 0.9, width * 0.025));
    el.querySelectorAll("[data-letter]").forEach((e) => {
      const k = reduced ? 1 : ease((local - 0.5 - Number(e.dataset.letter) * 0.1) / 1.2);
      e.style.opacity = k; e.style.transform = `translate3d(${(1 - k) * width * 0.035}px,${(1 - k) * width * 0.035}px,0) rotate(${(1 - k) * 5}deg)`;
    });
    el.querySelectorAll("[data-rule]").forEach((e) => { e.style.transform = `scaleX(${reduced ? 1 : ease((local - Number(e.dataset.rule)) / 0.9)})`; });
    el.querySelectorAll("[data-card]").forEach((e) => {
      const j = Number(e.dataset.card), v = reduced ? 1 : ease((local - 1.1 - j * 0.24) / 1.1);
      e.style.opacity = v * (1 - j * 0.15); e.style.transform = `translate3d(${(1 - v) * width * 0.08}px,0,0) rotateY(${(1 - v) * -16}deg) rotate(${j * 1.4}deg)`;
    });
    el.querySelectorAll("[data-signal]").forEach((e) => {
      const j = Number(e.dataset.signal), v = reduced ? 1 : ease((local - 1.3 - j * 0.3) / 0.7);
      e.style.opacity = v * 0.9; e.style.transform = `translateX(${(1 - v) * -width * 0.03}px)`;
    });
    const priority = el.querySelector("[data-priority]");
    if (priority) setReveal(priority, (local - 3.6) / 0.85, width * 0.028);
    el.querySelectorAll("[data-step]").forEach((e) => {
      const j = Number(e.dataset.step);
      setReveal(e, (local - 1.4 - j * 1.15) / 0.7, width * 0.02);
      const g = reduced ? 1 : smooth((local - 1.8 - j * 1.15) / 0.7);
      e.querySelector(".step-icon").style.boxShadow = `0 0 ${g * width * 0.015}px rgba(220,167,99,${g * 0.16})`;
    });
    const fill = el.querySelector(".rail-fill");
    if (fill) {
      const k = reduced ? 1 : clamp((local - 1.8) / 4);
      fill.style.transform = `scaleX(${k})`;
      const bead = el.querySelector(".rail-bead");
      bead.style.left = `${1.5 + k * 66}%`; bead.style.opacity = local > 1.8 && local < 6.1 && !reduced ? 1 : 0;
    }
    el.querySelectorAll("[data-product]").forEach((e) => {
      const j = Number(e.dataset.product), v = reduced ? 1 : ease((local - 1.8 - j * 0.45) / 1);
      e.style.opacity = v; e.style.transform = `translate3d(${(1 - v) * width * (j ? 0.04 : -0.04)}px,${(1 - v) * width * 0.015}px,0)`;
    });
  }

  function render(t) {
    let next = starts.findLastIndex((s) => t >= s);
    next = Math.max(0, next);
    const local = t - starts[next];
    if (next !== idx) {
      idx = next; geometry = points.map((_, i) => form(previous, time, i)); previous = next;
      $("scene-label").textContent = names[next];
      $("chapter-number").textContent = String(next + 1).padStart(2, "0") + " / 06";
    }
    draw(next, reduced ? 2 : local, t);
    scenes.forEach((_, i) => setScene(i, local));
    const wash = $("wash"), v = clamp(local / 0.9);
    wash.style.opacity = local < 0.9 && next > 0 && !reduced ? Math.sin(v * Math.PI) * 0.5 : 0;
    wash.style.transform = `translateX(${lerp(-110, 110, v)}%)`;
    $("film-progress").style.width = (t / TOTAL) * 100 + "%";
  }

  function tick(now) {
    rafId = 0;
    if (!playing) return;
    const dt = last ? Math.min((now - last) / 1000, 0.12) : 0;
    last = now;
    time += dt;
    if (time >= TOTAL) { time = 0; idx = -1; previous = 5; }
    render(time);
    rafId = requestAnimationFrame(tick);
  }

  function run() {
    if (rafId) cancelAnimationFrame(rafId);
    rafId = 0; last = 0;
    if (playing) rafId = requestAnimationFrame(tick); else render(time);
  }

  document.addEventListener("visibilitychange", () => { last = 0; });
  reduceQuery.addEventListener("change", (e) => { reduced = e.matches; playing = !reduced; run(); });
  new ResizeObserver(resize).observe(stage);
  resize(); render(0); run();
})();
