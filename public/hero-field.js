const glyphs = ["0", "1", "7", "9", "A", "F", "{", "}", ":", "+", "×", ">", "·", "[", "]"];

export function mountHeroField(canvas) {
  const context = canvas.getContext("2d");
  if (!context) return;
  const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)");
  const hero = canvas.parentElement;
  const spacing = 22;
  let width = 0;
  let height = 0;
  let cursor = null;
  let frame = 0;

  function draw(time) {
    frame = 0;
    if (!width || !height || document.hidden) return;
    const presence = cursor ? Math.max(0, 1 - (time - cursor.time) / 720) : 0;
    const radius = 154;
    const columns = Math.floor(width / spacing);
    const rows = Math.floor(height / spacing);
    const startX = (width - (columns - 1) * spacing) / 2;
    const startY = (height - (rows - 1) * spacing) / 2;
    context.clearRect(0, 0, width, height);
    context.font = "8px monospace";
    context.textBaseline = "middle";
    context.textAlign = "center";
    for (let row = 0, y = startY; row < rows; row++, y += spacing) {
      for (let column = 0, x = startX; column < columns; column++, x += spacing) {
        const seed = (row * 41 + column * 27) ^ (row * column * 11);
        const proximity = cursor ? Math.max(0, 1 - Math.hypot(x - cursor.x, y - cursor.y) / radius) : 0;
        const light = (proximity * presence) ** 2;
        context.fillStyle = `rgba(85, 230, 143, ${0.2 + light * 0.46})`;
        context.fillText(glyphs[seed % glyphs.length], x, y);
      }
    }
    if (presence > 0 && !reducedMotion.matches) schedule();
  }

  function schedule() {
    if (!frame && width && height) frame = requestAnimationFrame(draw);
  }

  new ResizeObserver(() => {
    ({ width, height } = canvas.getBoundingClientRect());
    const ratio = Math.min(devicePixelRatio || 1, 2);
    canvas.width = Math.round(width * ratio);
    canvas.height = Math.round(height * ratio);
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    cursor = null;
    schedule();
  }).observe(canvas);
  hero.addEventListener("pointermove", event => {
    if (reducedMotion.matches || event.pointerType === "touch") return;
    const bounds = canvas.getBoundingClientRect();
    cursor = { x: event.clientX - bounds.left, y: event.clientY - bounds.top, time: performance.now() };
    schedule();
  }, { passive: true });
  reducedMotion.addEventListener("change", () => {
    cursor = null;
    schedule();
  });
  document.addEventListener("visibilitychange", () => {
    cursor = null;
    if (!document.hidden) schedule();
  });
}
