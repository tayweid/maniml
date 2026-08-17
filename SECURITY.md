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
loaded in a browser can still attempt connections to localhost. ManimLive's app
control channel and each scene viewer therefore require both:

- an unguessable, process-local capability token; and
- a browser Origin on the server's exact allowlist.

Tokens are passed to a newly opened page in the URL fragment, which isn't sent
in the HTTP request. The page removes the fragment. Locally served pages retain
it only in that tab's session; the hosted page keeps it only in memory because
all projects on the GitHub Pages account share one web origin. Viewer tokens
are separate from the app-control token and expire with their respective
processes.

The hosted PWA must be paired with each new local daemon session. The desktop
launcher starts a freshly paired session when the user opens a file; the
`maniml app DIR --hosted` command remains an explicit fallback. Opening an old
installed PWA by itself grants no authority over a newly started daemon. Its
onboarding page may copy a one-time installation command to the clipboard, but
it cannot execute that command.

The toolbar's native picker is reachable only over the authenticated control
channel. A file selected in the OS dialog grants the daemon access to that
single canonical `.py` file for the life of the process; it does not disable
root confinement for sibling paths. Cancellation grants nothing. Desktop-open
sessions use an OS-assigned control port carried in the fragment alongside the
fresh capability so concurrent sessions do not share authorization.

When no engine is paired, the Open button may invoke the registered
`maniml://open` desktop URL. That URL accepts no file path or command; it can
only display the OS picker. This prevents an arbitrary website from turning a
custom-protocol navigation into unattended scene execution.

The dedicated `https://maniml.tayweid.io` origin is the launch target. It and
the legacy GitHub Pages origin are explicitly allowed during the transition.
No wildcard web origin is trusted. The hosted client and local daemon also
exchange an integer protocol version after authentication and refuse an
incompatible pairing.

Current Chromium releases separately require user permission before a public
website can connect to loopback. The hosted viewer issues a token-free `HEAD`
request for a static app asset so the browser can present that Local Network
Access prompt before the WebSocket handshake. Granting the browser permission
only makes the transport reachable: the WebSocket still requires its
unguessable viewer token and an exact allowed Origin. The probe never contains
the token, a scene path, or other local data.

### Exported scenes are public artifacts

`--export` creates a self-contained web player. Images and textures used by the
scene may be embedded in that output. Review the export directory before
publishing it.

## In scope for security reports

- Bypassing app or viewer authentication or Origin validation
- Causing a rejected scene path to be imported or executed
- Escaping the configured scene root without an explicit opt-in
- Reading frames, geometry, local paths, or logs without authorization
- Command injection in library-managed subprocesses
- Vulnerabilities in release automation or published artifacts

Running a deliberately malicious scene file that the user explicitly trusted
and opened is not, by itself, a sandbox escape because scene execution is not
advertised as sandboxed.
