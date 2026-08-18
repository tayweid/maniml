# Notes from Knuth on the local same-origin app

Written 2026-08-17 after Knuth (github.com/tayweid/knuth) spent a day
debugging its browser↔engine connection and ended up rebuilding it into the
shape maniml already has. Recorded here because the two projects are now the
same architecture, so the failures are transferable — and because maniml made
one deliberate choice differently, which is worth keeping deliberate.

## The shape both projects arrived at

A local Python process that serves the UI *and* runs the code, on one
loopback port, with the page and the socket sharing an origin. Installed by
pip, launched from a file double-click, kept alive by a login agent.

maniml got there first: "Collapse to a local, pip-only app", "Open
Finder-launched scenes in the app itself", "Run the engine as a login agent".
Knuth arrived on 2026-08-17 by deleting the alternative — its UI had been
hosted on GitHub Pages and talked *across* origins to a local engine, which
cost 1,466 lines of pairing machinery and a day of debugging before it went.

Everything below is what that day produced.

## The difference: how the token reaches the page

maniml mints a capability token and delivers it in the URL fragment
(`http://localhost:PORT/#token=...`), printed for the user to open. Knuth did
the same thing and it was the source of every bug it hit:

- The launcher opened the installed PWA's macOS app shim with that URL. A
  Chromium app shim **silently discards the URL** and loads the manifest
  `start_url` instead — the fragment never arrives. `open` still exits 0, so
  nothing could tell that delivery had failed.
- A window that was refused then **deleted the stored credential**, which was
  shared by every window on the origin. One rejected socket unpaired the
  whole browser, including every future double-click, recoverable only from a
  terminal.

Neither is exotic. Both come from the same root: a secret that has to travel
*into* the browser from outside is a delivery problem, and delivery can fail
silently.

**The cheap fix, if maniml keeps its token: stop putting it in the URL.** The
server that serves the page is the server that holds the token, so it can
embed it in the HTML it hands out:

    <script>window.__MANIML_TOKEN__ = "...";</script>

No fragment, no printed URL to copy, nothing to drop, and a page that is
refused can simply re-fetch. "Stuck unauthorized with no way back" stops being
reachable, which is the property that actually matters.

## Where the threat models differ — a real choice, not an oversight

maniml's `web/security.py` says loopback is a network boundary, not an
authorization boundary: any program on the machine can reach 127.0.0.1, so it
keeps a token. That is correct, and Knuth decided the opposite. The split:

| Attacker | Origin check | Token |
|---|---|---|
| A web page on another site | **blocks it** — browsers set `Origin`, pages cannot forge it | redundant |
| Another program on this machine | no help — it can forge any header | **blocks it, but only if the token never reaches the page** |

That last cell is the whole decision. If the token is embedded in the served
HTML, any local program can `GET /` and read it, so it defends against
nothing that the origin check didn't already cover. Keeping it meaningful
means keeping it out-of-band — which is what the printed URL buys, and what
it costs a user step for.

Knuth judged that a process running as you can already run `python`, so the
token wasn't earning its complexity, and deleted it. maniml may reasonably
judge otherwise — scenes execute arbitrary code too. The point is that
**embedding the token and keeping the token are different decisions**: doing
the first without noticing turns the second into decoration.

## Measurements that transfer

Run against Chrome 151 on macOS 26, so they should hold for maniml's viewer:

- A PWA installed from `http://127.0.0.1:PORT` **can** register OS file
  handlers, and a double-click delivers the file through `launchQueue`.
- That works **with the server stopped** — the service worker serves the
  shell and the file handle comes from the OS, not the server. So a
  double-click can open the app, show the file, and say "start the engine"
  rather than failing blankly.
- `connect-src 'self'` in a CSP **does** cover a WebSocket back to the same
  origin. Verified by running on a non-default port, where a hardcoded
  `ws://127.0.0.1:<port>` would have failed. Deriving both the socket URL and
  the CSP from `window.location` makes the app port-agnostic.
- `open -a <App> <url>` cannot hand a URL to a Chromium PWA. If maniml ever
  launches its viewer that way, it will hit exactly the bug above.
- A pip install from a GitHub archive is ~1.8s cold. Shipping the frontend
  inside the wheel costs nothing noticeable and removes app/engine version
  skew entirely.

## The one that cost the most

Do not let a client delete its own credential because one connection was
refused. A refusal is not proof the credential is dead, and if that
credential is shared across windows, one bad socket takes out the whole
browser. Knuth's fix was to keep it: a stale credential fails harmlessly and
gets overwritten, while a deleted good one costs the user the app.

Knuth's full reasoning is in its `SAME_ORIGIN.md`.
