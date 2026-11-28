Run `streaming.cjs` from a **disposable local Compose test stack** with the current backend, frontend and migrations. It creates a temporary ordinary user and three visible models, then removes them. It uses the actual API, database, Nginx, Chromium and CSRF-protected web session. The mock OpenAI-compatible service runs on a random loopback port inside the backend container. The runner controls when each model finishes and checks that stopping a conversation closes its upstream socket. It gates final text until the page has rendered two reasoning deltas, then checks the selected effort, the stored trace after reload, and the mobile layout in both themes. No provider key is needed.

Install Playwright outside the application and run the test with its Chromium or an installed system Chromium.

```sh
npm install --prefix /tmp/portal-browser playwright
NODE_PATH=/tmp/portal-browser/node_modules CHROMIUM_BIN=/usr/bin/chromium node tests/browser/streaming.cjs
```

Set `PORTAL_TEST_URL` if the local frontend uses a port other than 8080. Compose commands run in the project root and honor `COMPOSE_PROJECT_NAME`, `COMPOSE_FILE` and the Docker CLI configuration. HTTP proxies in the test backend should bypass loopback.

The workspace checks exercise one, two and three models, model search and thinking settings, keyboard submission, draft preparation after Stop, history search/rename/delete, safe Markdown and highlighted code copy. The runner verifies that typing sends no estimate requests, stopping one comparison model preserves its siblings, and a regenerated answer is stored in a new revision. Pins, response feedback, the personal spending report, and the Markdown download use the authenticated application. Chromium checks document overflow at 320, 360, 390, 640, 768, 1024, 1440 and 1920 CSS pixels in both themes. A gated long response checks that reading older messages suspends auto-scroll. To capture test views, set `PORTAL_SCREENSHOTS` to an existing output directory outside the repository.

The runner also syncs the loopback HTTP model catalog using an exact, test-process-only local origin, enables the two new models and reloads the SPA. It checks that an unknown model exposes no effort selector and that the catalog's explicit `xhigh` value reaches the upstream chat request.

The revision scenario edits the first turn of a three-model chat and switches between branches before and after a reload. It checks the inherited model settings, restores a follow-up turn and verifies that browsing makes no additional provider calls. It also checks an incomplete streamed formula, a completed KaTeX fraction, literal code, Persian text direction and local horizontal scrolling for a long formula at 320 px in both themes.
