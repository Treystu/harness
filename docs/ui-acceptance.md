# GUI First-Use Acceptance Checklist (`harness serve` / `harness desktop`)

This document is the single acceptance reference for first-use authentication,
recovery, and loopback serving across `harness serve` and `harness desktop`
(`harness-desktop`). See [security.md](security.md) for the security model and
[ui-readiness.md](ui-readiness.md) for API envelopes and pane behavior.

## Loopback Ports and Routes

| Surface | Default bind / target | Auth requirement | Override |
|---|---|---|---|
| `harness serve` (`harness/server.py`, `make_server`) | `127.0.0.1:8767` | Required for all `/api/*` routes (`401` unauthenticated, `200` authenticated) | `--port <port>` (e.g. `--port 8800`) or `HARNESS_UI_PORT` |
| `harness desktop` / `harness-desktop` (`harness/ui.py`) | `127.0.0.1:8767` | Required for all `/api/*` routes (reuses owner token via URL fragment) | `--port <port>` or `HARNESS_UI_PORT` |
| External `media serve` (when run separately) | `127.0.0.1:8765` | Optional bearer token (`MEDIA_TOKEN`) | `MEDIA_BASE_URL` or server `--port` |

Key endpoint and default-port facts:

- **One UI port, one owner (`#655`):** `harness.config.ui_port()` holds the
  single default (`127.0.0.1:8767`); `make_server`, `harness serve`,
  `harness desktop` and `harness doctor --gui-port` all read it, and
  `HARNESS_UI_PORT` sets it once for all of them. A `--port` flag overrides it
  per command. Port `8800` is used only when passed explicitly.
- **`harness desktop` takes the same port as `harness serve`:** the desktop
  shell runs the same server, so the two agree. Run one at a time, or give the
  second instance its own `--port` (for example `--port 8768`).
- **Media keeps its own port (`#566`):** external `media serve` owns `8765` by
  design (override with `MEDIA_BASE_URL`), so the UI and the media service can
  run together. An older or explicitly configured Harness UI still on `8765` is
  caught by `harness/media_client.py` before a media operation or token is sent
  (`MediaEndpointMismatch`); move that UI with `--port 8767` (see
  [media.md](media.md)).
- **`GET /api/status` requires auth (`401` anonymous, `200` authenticated):**
  static shell assets (`/`, `/app.js`, `/app.css`, `/panes.js`, `/panes.css`)
  return `200` without credentials so the auth modal can load, while
  `/api/status`, `/api/settings`, `/api/capabilities`, and all other `/api/*`
  endpoints fail closed with `401` until `X-Harness-Auth` or
  `Authorization: Bearer <token>` carries the owner credential.

## Auth Artifacts (`ui_auth.py`)

When `harness serve` or `harness desktop` starts without disabling auth,
`harness/ui_auth.py` creates three files in the operator config directory:

1. `desktop_token` — persistent owner credential (owner-only permissions on
   POSIX; profile ACL on Windows). Startup fails closed if persistence fails so
   the operator is never locked out.
2. `gui-open.url` — private clickable recovery shortcut pointing to the
   bound loopback URL with `#token=<owner-token>` in the fragment (fragments stay
   client-side and are never sent on HTTP requests or logged by `server.py`).
3. `gui-auth-handoff.txt` — token-free human-readable recovery guide pointing to
   `gui-open.url` and `harness serve --open`.

## First-Use Acceptance Flow (No Stranded User)

Every check below must pass before declaring GUI onboarding healthy:

1. **Fresh browser opens unauthenticated shell:** opening `http://127.0.0.1:8765/`
   without a fragment shows the auth modal (`auth-modal`) with plain-language
   recovery text mentioning `gui-open.url` and `harness serve --open`; unauthenticated
   `GET /api/status` returns `401`.
2. **Empty pairing submit gives immediate client guidance:** submitting the
   pairing box empty does not hit the server blindly; the UI displays
   `"Enter the 10-character pairing code shown in Harness."`.
3. **Invalid or reused pairing code returns `401` cleanly:** entering an
   expired, reused, or invalid 10-character code calls `POST /api/auth/pair/redeem`
   and surfaces clear `401` retry guidance in the modal without losing access to
   recovery instructions.
4. **Signed-in window pairs a second browser:** in an already authenticated
   window, clicking create pairing code calls `POST /api/auth/pair/create`
   (authenticated via `X-Harness-Auth`) to mint a single-use, short-TTL 10-char
   code; redeeming it via `POST /api/auth/pair/redeem` in the fresh browser
   grants the token and transitions the fresh browser to `200` on `/api/status`.
5. **Private shortcut recovery (`gui-open.url`):** closing all signed-in tabs
   and opening `gui-open.url` (even after restart with the persistent token)
   restores authenticated UI access cleanly.
6. **Restart recovery (`harness serve --open`):** stopping `harness serve` and
   restarting with `harness serve --open` reuses `desktop_token`, rewrites
   `gui-open.url` with the active port, and opens a signed-in session without
   requiring manual token entry.
