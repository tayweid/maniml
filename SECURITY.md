# Security policy

ManimLive is currently alpha software preparing for a wider public release.
Security-sensitive interfaces and defaults are expected to remain conservative
even when compatibility escape hatches are available.

## Supported versions

Before the first public release, security fixes are made on `main`; development
snapshots are not supported as stable releases. The supported release line will
be documented here when the first version is published.

## Reporting a vulnerability

Please use GitHub's private vulnerability-reporting feature for this
repository when it is available. Do not publish exploit details in a public
issue before a fix is ready. Include the affected version or commit, platform,
reproduction steps, impact, and any suggested mitigation.

## Trust model

### Scene files are trusted code

A ManimLive scene is a Python program. Loading it executes its module-level
code, and running it may invoke Python packages and external tools such as TeX
and ffmpeg. Scene subprocesses isolate crashes; they are not an operating-system
sandbox. Only open scene files you would be willing to run with Python directly.

Scenes opened through `maniml app` run in a dedicated process group. Normal app
exit, Ctrl-C, and SIGTERM terminate the scene and its descendant processes with
bounded escalation. This cleanup prevents accidentally orphaned tools; it does
not constrain a malicious scene or turn the process group into a sandbox.

`maniml app DIR` treats `DIR` as the authorized scene root. It rejects files
outside that root by default, including symlinks that resolve outside it. The
`--allow-outside-root` option is an explicit compatibility escape hatch.

Scene files may refer to images, vectors, and sounds by HTTP(S) URL. Those
downloads have a 15-second socket timeout, a 60-second transfer deadline, and a
256 MiB per-asset limit. Completed downloads are cached by URL and promoted
atomically; failed or truncated responses are discarded. ManimLive does not
authenticate remote asset publishers or promise that a URL's content is safe,
so scene authors remain responsible for the URLs they use.

### Browser clients start untrusted

Binding a service to loopback prevents remote network access, but websites
loaded in a browser can still attempt connections to localhost. **The Origin
check is what stops them.** Every ManimLive server — the app's control channel
and each scene viewer — serves its page and accepts its WebSocket on one
loopback port, and completes a handshake only when the request carries that
server's exact origin. Browsers set `Origin` themselves and a page cannot forge
it, so no website can drive the engine regardless of the port it guesses. A
request with no `Origin` at all is refused for the same reason: it is not the
page this server handed out.

There is no capability token, and the address (`http://localhost:8685/`)
carries no secret. That is a deliberate narrowing of the threat model rather
than an oversight, so it is worth stating what it does and does not cover:

| Attacker | Defended | How |
|---|---|---|
| A website in your browser | yes | It cannot forge `Origin`, and cannot read a cross-origin response |
| Another machine on the network | yes | Every server binds 127.0.0.1 only |
| Another program running as you | **no** | It can forge any header, and it can equally well run `python` itself |

A token defends only that third row, and only for as long as it never reaches
the page through the served HTML — the moment it does, any local program can
read it with a plain `GET /`. Keeping it meaningful therefore meant delivering
it out of band, which made launching a delivery problem and left a rejected
page with no way back except a terminal. Against an attacker that already has
the authority to run Python as you, that price bought very little, so the
token was removed.

Scene root confinement is unchanged and is the boundary that still matters
in daily use: `maniml app DIR` rejects paths outside `DIR`, including symlinks
that resolve outside it, unless `--allow-outside-root` is given.

The toolbar's native picker is reachable only over the control channel. A file
selected in the OS dialog grants the running app access to that single
canonical `.py` file for the life of the process; it does not disable root
confinement for sibling paths. Cancellation grants nothing.

Each page is served with a Content-Security-Policy of `default-src 'self'` and
`connect-src 'self'`. Because the page and its socket share an origin exactly,
that policy genuinely confines the page to the engine that served it: there is
no second origin, host, or port it is permitted to reach.

### Exported scenes are public artifacts

`--export` creates a self-contained web player. Images and textures used by the
scene may be embedded in that output. Review the export directory before
publishing it.

## In scope for security reports

- Bypassing Origin validation on the app or a scene viewer
- Causing a rejected scene path to be imported or executed
- Escaping the configured scene root without an explicit opt-in
- Reading frames, geometry, local paths, or logs without authorization
- Command injection in library-managed subprocesses
- Vulnerabilities in release automation or published artifacts

Running a deliberately malicious scene file that the user explicitly trusted
and opened is not, by itself, a sandbox escape because scene execution is not
advertised as sandboxed.
