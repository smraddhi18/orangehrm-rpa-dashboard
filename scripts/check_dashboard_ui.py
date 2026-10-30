"""Live local UI smoke check at a narrow viewport; no OrangeHRM submission."""

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
            page = browser.new_page(viewport={"width": 390, "height": 844})
            errors: list[str] = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(os.getenv("DASHBOARD_URL", "http://127.0.0.1:8000/"))
            page.get_by_role("button", name="Run automation").click()
            width = page.evaluate("document.documentElement.scrollWidth")
            validation = page.locator(".field-error").all_inner_texts()
            page.screenshot(
                path=str(ROOT / "screenshots" / "dashboard_mobile.png"), full_page=True
            )
            result = {
                "viewport_width": 390,
                "page_width": width,
                "validation_errors": validation,
                "console_errors": errors,
            }
            print(json.dumps(result, indent=2))
            assert width <= 390
            assert len([error for error in validation if error]) == 5
            assert not errors
        finally:
            browser.close()


if __name__ == "__main__":
    main()
