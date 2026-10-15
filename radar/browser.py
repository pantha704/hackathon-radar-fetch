"""Browser backend plumbing for Hackathon Radar.

Points Playwright's browser resolution at the repo-local ``.pw-browsers``
symlink tree (built by ``scripts/provision_browsers.sh``), which maps the
Playwright revision this venv expects to the CloakBrowser binary. The env
default is set at MODULE level, before any crawl4ai/playwright import, so
every later browser launch in this process resolves the cloak binary.

crawl4ai/playwright themselves are imported lazily by `radar.fetch`.
"""

import os
from pathlib import Path

from radar.config import ROOT

# Repo-local Playwright browser tree (symlinks -> CloakBrowser). Rebuild with
# scripts/provision_browsers.sh; the tree is gitignored.
PW_BROWSERS_DEFAULT = ROOT / ".pw-browsers"

# Must happen before crawl4ai/playwright read it (both read at launch time, but
# keep the "before any crawl4ai import" ordering anyway: this module is the
# single place that owns the env default).
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(PW_BROWSERS_DEFAULT))

# CloakBrowser (stealth Chromium) binary. Override with RADAR_CLOAK_BIN for
# e.g. a newer build.
DEFAULT_CLOAK_BIN = "/home/ubuntu/.cloakbrowser/chromium-146.0.7680.177.5/chrome"
CLOAK_BIN = os.environ.get("RADAR_CLOAK_BIN", DEFAULT_CLOAK_BIN)


def pw_browsers_path() -> Path:
    """Current Playwright browser tree, read from the env at call time."""
    return Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", str(PW_BROWSERS_DEFAULT)))


def ensure_pw_browsers() -> Path:
    """Return the provisioned ``.pw-browsers`` tree or raise a helpful error.

    The tree is what makes crawl4ai (dedicated mode) launch the CloakBrowser
    binary instead of downloading a stock Chromium — see docs/spike-m0.md.
    """
    path = pw_browsers_path()
    if not path.is_dir() or not any(path.glob("chromium-*")):
        raise RuntimeError(
            f"Playwright browser tree missing or incomplete at {path}. "
            "Run scripts/provision_browsers.sh to link the CloakBrowser "
            "binary into .pw-browsers (or unset PLAYWRIGHT_BROWSERS_PATH)."
        )
    return path
