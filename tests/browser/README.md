Run `streaming.cjs` from a **disposable local Compose test stack** with the current backend, frontend and migrations. It creates a temporary ordinary user and three visible models, then removes them. It uses the actual API, database, Nginx, Chromium and CSRF-protected web session. The mock OpenAI-compatible service runs on a random loopback port inside the backend container. The runner controls when each model finishes and checks that stopping a conversation closes its upstream socket. No provider key is needed.

Install Playwright outside the application and run the test with its Chromium or an installed system Chromium.

```sh
npm install --prefix /tmp/portal-browser playwright
NODE_PATH=/tmp/portal-browser/node_modules CHROMIUM_BIN=/usr/bin/chromium node tests/browser/streaming.cjs
```

Set `PORTAL_TEST_URL` if the local frontend uses a port other than 8080. Compose commands run in the project root and honor `COMPOSE_PROJECT_NAME`, `COMPOSE_FILE` and the Docker CLI configuration. HTTP proxies in the test backend should bypass loopback.
