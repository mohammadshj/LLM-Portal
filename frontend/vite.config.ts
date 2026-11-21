import { createRequire } from "node:module";
import { defineConfig } from "vite";
export default defineConfig({
  // Parse KaTeX output as an AST. The browser entry parses inline styles through
  // template.innerHTML and triggers CSP even on a detached template.
  resolve: {
    alias: {
      "hast-util-from-html-isomorphic": createRequire(import.meta.url).resolve(
        "hast-util-from-html-isomorphic",
      ),
    },
  },
  // Nginx serves fonts under font-src 'self', including small KaTeX glyph sets.
  build: { assetsInlineLimit: 0 },
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/admin": "http://127.0.0.1:8000",
      "/static": "http://127.0.0.1:8000",
    },
  },
});
