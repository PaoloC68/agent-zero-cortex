# AZ Browser Plugin — Google OAuth2 Login

## The Problem

Google blocks OAuth2 sign-in flows inside Playwright/Chromium because it detects automation. Error: "This browser or app may not be secure."

## Root Cause

AZ's `_browser` plugin launches Chromium with default Playwright args — `navigator.webdriver = true` is left set. Google detects this at the OAuth redirect level and blocks sign-in before credentials can even be entered. A persistent profile does NOT help — the block happens before any cookies are checked.

## The Fix — Stealth Extension

A tiny unpacked Chrome extension that patches automation fingerprints at `document_start` (before any page JS runs).

### Files deployed on homelab (LXC 500)

```
/opt/agent-zero/data/usr/plugins/_browser/extensions/stealth/
  manifest.json   — MV3 extension, content_scripts world=MAIN, run_at=document_start
  stealth.js      — patches navigator.webdriver, plugins, languages
```

### stealth.js patches
```javascript
Object.defineProperty(navigator, "webdriver", { get: () => undefined });
Object.defineProperty(navigator, "plugins", { get: () => [1,2,3,4,5] });
Object.defineProperty(navigator, "languages", { get: () => ["en-US","en"] });
```

### Config registered at
```
/opt/agent-zero/data/usr/plugins/_browser/config.json
{
  "extension_paths": ["/a0/usr/plugins/_browser/extensions/stealth"],
  ...
}
```

Note: path uses `/a0/` prefix (container path), not `/opt/agent-zero/data/`.

## How to Use Google OAuth After Fix

1. Open AZ browser canvas in web UI
2. Ask AZ: *"Open accounts.google.com in the browser"*
3. Log in manually in the browser canvas
4. Session cookie saved in persistent profile — works forever after

## Persistent Profile Location

```
/a0/tmp/browser/sessions/<context_id>/   (inside container)
/opt/agent-zero/data/tmp/browser/sessions/<context_id>/   (on host)
```

AZ uses `launch_persistent_context()` — same agent context = same cookies across sessions.

## If Google Still Blocks After Stealth Extension

Additional fingerprints to patch in stealth.js:
```javascript
// Chrome runtime object
window.chrome = { runtime: {} };

// Permission query (real browsers return 'prompt' for notifications)
const originalQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (params) =>
  params.name === 'notifications'
    ? Promise.resolve({ state: Notification.permission })
    : originalQuery(params);

// WebGL vendor/renderer
const getParameter = WebGLRenderingContext.prototype.getParameter;
WebGLRenderingContext.prototype.getParameter = function(parameter) {
  if (parameter === 37445) return 'Intel Inc.';
  if (parameter === 37446) return 'Intel Iris OpenGL Engine';
  return getParameter.call(this, parameter);
};
```

## Key Source Files

- `plugins/_browser/helpers/runtime.py` — `_start()` uses `launch_persistent_context`, `profile_dir` property
- `plugins/_browser/helpers/config.py` — `build_browser_launch_config()`, `BASE_BROWSER_ARGS`, extension loading via `--load-extension=` and `--disable-extensions-except=`
- `plugins/_browser/default_config.yaml` — `extension_paths: []` default
