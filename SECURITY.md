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

`maniml app DIR` treats `DIR` as the authorized scene root. It rejects files
outside that root by default, including symlinks that resolve outside it. The
`--allow-outside-root` option is an explicit compatibility escape hatch.

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

The hosted PWA must be paired with each new local daemon session. Start it with
`maniml app DIR --hosted`; opening an old installed PWA by itself grants no
authority over a newly started daemon.

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
