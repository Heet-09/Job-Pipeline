"""Browser session helper. Persistent profile dir keeps login cookies; tests pass their own page."""
from contextlib import contextmanager
from pathlib import Path

from jobagent.flows.f4_formfill.guards import BLOCK_SUBMIT_JS


@contextmanager
def open_page(headless: bool = True, user_data_dir: Path | None = None):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        if user_data_dir:
            ctx = p.chromium.launch_persistent_context(str(user_data_dir), headless=headless)
            browser = None
        else:
            browser = p.chromium.launch(headless=headless)
            ctx = browser.new_context(viewport={"width": 1280, "height": 900})
        ctx.add_init_script(BLOCK_SUBMIT_JS)
        try:
            yield ctx.new_page()
        finally:
            ctx.close()
            if browser:
                browser.close()
