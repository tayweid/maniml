# Release process

ManimLive doesn't publish automatically. The current release workflow builds a
candidate artifact for manual inspection only. Add a PyPI publishing job after
the package name, protected GitHub environment, and PyPI Trusted Publisher are
configured and the initial release gate below is satisfied.

## Initial public-release gate

1. Confirm CI and CodeQL pass on the release commit.
2. Publish a project-specific code of conduct with a private maintainer contact;
   do not point reports at ManimCommunity's moderators.
3. Enable GitHub private vulnerability reporting and verify the instructions in
   `SECURITY.md` work for a non-maintainer.
4. Run the full windowed interactive suite on macOS.
5. Run `uv audit --locked` against the resolved development environment and
   address or document every known vulnerability.
6. Update the version and `CHANGELOG.md`.
7. Run the **Build release candidate** workflow.
8. Download the artifact and inspect the wheel and source archive.
9. Install the wheel in a clean Python 3.11 environment and a clean Python
   3.14 environment; run one native, one browser, one render, and one export
   smoke scene.
10. Publish the exact candidate to TestPyPI and repeat the clean installation
   smoke test from TestPyPI.
11. Create an annotated release tag from the reviewed commit.
12. Approve production publishing through a protected `pypi` GitHub
    environment using PyPI Trusted Publishing.

Never publish from an unreviewed working tree, rebuild after approval, or use a
long-lived PyPI API token.
