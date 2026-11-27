// Runs before first paint (classic script, allowed by the CSP) so an explicit dark/light choice never flashes.
try {
  var t = JSON.parse(localStorage.getItem("hs.theme") || '"system"');
  if (t === "light" || t === "dark") document.documentElement.setAttribute("data-theme", t);
} catch (e) { /* storage blocked: follow the system setting */ }
