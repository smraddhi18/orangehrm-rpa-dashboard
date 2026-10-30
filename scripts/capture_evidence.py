"""Optional live dashboard test. Requires a running local server and demo credentials.

The screenshots and CSV come from a real dashboard-triggered workflow.
"""

from __future__ import annotations

import csv
import json
import os
from pathlib import Path
from uuid import uuid4

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SCREENSHOTS = ROOT / "screenshots"
URL = os.getenv("DASHBOARD_URL", "http://127.0.0.1:8000/")


def main() -> None:
    username = os.environ["ORANGEHRM_USERNAME"]
    password = os.environ["ORANGEHRM_PASSWORD"]
    employee_id = "OL" + uuid4().hex[:8].upper()
    SCREENSHOTS.mkdir(exist_ok=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(
                viewport={"width": 1440, "height": 1100}, device_scale_factor=1
            )
            page.goto(URL, wait_until="domcontentloaded")
            page.locator("#username").fill(username)
            page.locator("#password").fill(password)
            page.locator("#first_name").fill("OrangeLab")
            page.locator("#last_name").fill("Assessment")
            page.locator("#employee_id").fill(employee_id)
            page.screenshot(
                path=str(SCREENSHOTS / "dashboard_before.png"), full_page=True
            )
            page.get_by_role("button", name="Run automation").click()
            page.locator("#live-preview").wait_for(state="visible")
            page.wait_for_function(
                "() => ['success', 'partial', 'failed'].some(s => "
                "document.querySelector('#status-badge').classList.contains(s))",
                timeout=600000,
            )
            page.locator("#preview-image").wait_for(state="visible", timeout=10000)
            status = page.locator("#status-badge").get_attribute("class")
            path = SCREENSHOTS / (
                "dashboard_after.png"
                if "success" in status
                else "dashboard_after_failed.png"
            )
            page.screenshot(path=str(path), full_page=True)
            result = {
                "employee_id": employee_id,
                "status": page.locator("#status-text").inner_text(),
                "result": page.locator("#result-banner").inner_text(),
                "note": page.locator("#result-note").inner_text(),
                "failure_details": page.locator("#failure-list").inner_text(),
                "preview_visible": page.locator("#preview-image").is_visible(),
                "extracted_rows": page.locator("#employee-rows tr").count(),
                "csv_available": page.locator("#download-link").is_visible(),
                "steps_success": page.locator("#progress-list li.success").count(),
                "screenshot": str(path),
            }
            if "success" not in status:
                print(json.dumps(result, indent=2))
                raise SystemExit(1)
            assert result["preview_visible"]
            assert result["csv_available"]
            assert result["steps_success"] == 8
            export_href = page.locator("#download-link").get_attribute("href")
            assert export_href is not None
            job_id = export_href.split("/")[-2]
            csv_path = ROOT / "exports" / f"{job_id}.csv"
            with csv_path.open(encoding="utf-8-sig", newline="") as stream:
                reader = csv.DictReader(stream)
                assert reader.fieldnames == ["Employee ID", "First Name", "Last Name"]
                rows = list(reader)
            assert len(rows) == result["extracted_rows"]
            assert any(
                row
                == {
                    "Employee ID": employee_id,
                    "First Name": "OrangeLab",
                    "Last Name": "Assessment",
                }
                for row in rows
            )
            result["csv_rows"] = len(rows)
            result["csv_path"] = str(csv_path)
            print(json.dumps(result, indent=2))
        finally:
            browser.close()


if __name__ == "__main__":
    main()
