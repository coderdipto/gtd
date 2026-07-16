(function () {
  function currentTheme() {
    var stored = localStorage.getItem("gtd-theme");
    if (stored === "dark" || stored === "light") return stored;
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }

  function paint(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    document.querySelectorAll("[data-theme-toggle]").forEach(function (btn) {
      btn.setAttribute("aria-label", theme === "dark" ? "Switch to light theme" : "Switch to dark theme");
      var sunIcon = btn.querySelector("[data-theme-icon='sun']");
      var moonIcon = btn.querySelector("[data-theme-icon='moon']");
      if (sunIcon) sunIcon.classList.toggle("hidden", theme !== "dark");
      if (moonIcon) moonIcon.classList.toggle("hidden", theme === "dark");
    });
  }

  // base.html's header (and the toggle button in it) is part of the body
  // content hx-boost swaps on every navigation, so state has to be
  // recomputed on htmx:load too, not just DOMContentLoaded - same gotcha
  // documented in calendar-time-panel.js / sortable-lists.js.
  document.addEventListener("DOMContentLoaded", function () { paint(currentTheme()); });
  document.addEventListener("htmx:load", function () { paint(currentTheme()); });

  document.addEventListener("click", function (event) {
    var btn = event.target.closest("[data-theme-toggle]");
    if (!btn) return;
    var next = currentTheme() === "dark" ? "light" : "dark";
    localStorage.setItem("gtd-theme", next);
    paint(next);
  });
})();
