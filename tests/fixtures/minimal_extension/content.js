// Content script runs in ISOLATED world; we communicate to MAIN world
// via a DOM marker so page.evaluate() (MAIN world) can detect it.
console.log("[stealth-ext-marker] content.js running on", location.href);
try {
  const meta = document.createElement("meta");
  meta.setAttribute("name", "stealth-ext-marker");
  meta.setAttribute("content", "loaded");
  (document.head || document.documentElement).appendChild(meta);
  console.log("[stealth-ext-marker] marker appended");
} catch (e) {
  console.error("[stealth-ext-marker] failed:", e);
}
