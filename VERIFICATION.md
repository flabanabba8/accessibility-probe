# Verification

- Mixed-case protected-directory fixtures passed on Linux and native Windows; no real credentials were used. This is not a full platform or publication audit.

- Native Windows Python 3.14 identified a missing image alt attribute in a synthetic static HTML file. No Windows browser walkthrough was run.
- Earlier Linux fixtures covered static labeling heuristics, a real headless focus journey, blocked local network requests and credential-scrubbed browser process behavior.
- The Playwright requirement allows 1.64.x, including the 1.64.0 version pinned by an optional Hermes component. Eight Linux tests passed with 1.64.1; a fresh warmed-cache Hermes profile enabled the plugin and all eight passed in its managed Playwright 1.64.0 environment. A prior exact 1.64.1 pin caused a Hermes dependency conflict. This is not a fresh online bootstrap or a Windows browser test.
- A self-authored two-button fixture returned two expected matches from the plugin. A separate headless browser run with JavaScript and network requests disabled was visually inspected after each Tab; the visible focus outlines followed the same order. The separate screenshots are not produced or evaluated by the plugin and do not establish accessibility conformance.
- Static checks do not establish accessibility conformance. Dynamic sites, screen readers, visual focus, native Windows browser behavior, a reviewed demo and a complete publication audit remain unverified.
