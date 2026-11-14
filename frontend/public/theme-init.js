// Apply the theme before CSS/React paint; external script works with script-src 'self'.
(() => {
  let saved;
  try {
    saved = localStorage.getItem("portal-theme");
  } catch {
    // Storage can be unavailable in private or restricted browsing.
  }
  const theme =
    saved === "light" || saved === "dark"
      ? saved
      : matchMedia("(prefers-color-scheme: dark)").matches
        ? "dark"
        : "light";
  document.documentElement.dataset.theme = theme;
  document.querySelector('meta[name="theme-color"]').content =
    theme === "dark" ? "#121c18" : "#f8faf9";
})();
