"""Live duplicate-ID check through the dashboard; requires demo credentials."""

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
            page.locator("#username").fill(os.environ["ORANGEHRM_USERNAME"])
            page.locator("#password").fill(os.environ["ORANGEHRM_PASSWORD"])
            page.locator("#first_name").fill("OrangeLab")
            page.locator("#last_name").fill("Assessment")
            page.locator("#employee_id").fill(os.environ["EXISTING_EMPLOYEE_ID"])
            page.get_by_role("button", name="Run automation").click()
            page.wait_for_function(
                "() => document.querySelector('#status-badge').classList.contains('failed')",
                timeout=600000,
            )
            page.locator("#preview-image").wait_for(state="visible", timeout=10000)
            states = {
                key: page.locator(f'#progress-list [data-key="{key}"]').get_attribute(
                    "class"
                )
                for key in ("creation", "verification", "logout")
            }
            result = {
                "status": page.locator("#status-text").inner_text(),
                "reason": page.locator("#failure-list").inner_text(),
                "steps": states,
            }
            page.screenshot(
                path=str(ROOT / "screenshots" / "dashboard_duplicate_id.png"),
                full_page=True,
            )
            print(json.dumps(result, indent=2))
            assert "already exists" in result["reason"].lower()
            assert "Next:" in result["reason"]
            assert states == {
                "creation": "failed",
                "verification": "skipped",
                "logout": "success",
            }
        finally:
            browser.close()


if __name__ == "__main__":
    main()
