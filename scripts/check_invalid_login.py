"""Live failure-path check through the dashboard; does not create an employee."""

from __future__ import annotations

import json
import os
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": 1440, "height": 1100})
            page.goto(os.getenv("DASHBOARD_URL", "http://127.0.0.1:8000/"))
            page.locator("#username").fill("Admin")
            page.locator("#password").fill("deliberately-invalid")
            page.locator("#first_name").fill("Never")
            page.locator("#last_name").fill("Created")
            page.locator("#employee_id").fill("BADLOGIN1")
            page.get_by_role("button", name="Run automation").click()
            page.locator("#live-preview").wait_for(state="visible")
            page.locator("#preview-image").wait_for(state="visible", timeout=30000)
            page.screenshot(
                path=str(ROOT / "screenshots" / "dashboard_live_preview.png"),
                full_page=True,
            )
            page.wait_for_function(
                "() => document.querySelector('#status-badge').classList.contains('failed')",
                timeout=60000,
            )
            states = {
                key: page.locator(f'#progress-list [data-key="{key}"]').get_attribute(
                    "class"
                )
                for key in ("login", "creation", "logout")
            }
            result = {
                "status": page.locator("#status-text").inner_text(),
                "reason": page.locator("#failure-list").inner_text(),
                "steps": states,
                "csv_available": page.locator("#download-link").is_visible(),
                "preview_visible": page.locator("#preview-image").is_visible(),
            }
            path = ROOT / "screenshots" / "dashboard_invalid_login.png"
            page.screenshot(path=str(path), full_page=True)
            print(json.dumps(result, indent=2))
            assert states == {
                "login": "failed",
                "creation": "skipped",
                "logout": "skipped",
            }
            assert "OrangeHRM rejected the login credentials" in result["reason"]
            assert "Next:" in result["reason"]
            assert not result["csv_available"]
            assert result["preview_visible"]
        finally:
            browser.close()


if __name__ == "__main__":
    main()
