"""Browser workflow against the OrangeHRM demo (observed OS 5.9 UI)."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from app.jobs import JobStore
from app.schemas import STEP_NAMES, AutomationInput, Employee
from app.services.employee_export import employees_to_csv

if TYPE_CHECKING:
    from playwright.sync_api import Page

URL = "https://opensource-demo.orangehrmlive.com"
EXPORT_DIR = Path(__file__).resolve().parents[2] / "exports"
logger = logging.getLogger(__name__)


class AutomationFailure(Exception):
    """A safe, user-facing workflow error."""

    def __init__(self, reason: str, next_action: str = "") -> None:
        super().__init__(reason)
        self.next_action = next_action


NEXT_ACTIONS = {
    "opening": "Check your internet connection and that the OrangeHRM demo opens in a browser, then retry.",
    "login": "Check the username and password entered in the dashboard, then start a new run.",
    "pim": "Check that the account can open PIM in OrangeHRM, then retry.",
    "creation": "Search PIM for this employee ID before retrying; Save may have completed despite the interruption.",
    "verification": "Inspect the saved record in PIM before retrying to avoid creating a duplicate.",
    "extraction": "The employee may already be saved. Review PIM and try a new run only if needed.",
    "logout": "If OrangeHRM remains signed in, log out manually from its profile menu.",
}


def _capture_preview(store: JobStore, job_id: str, page: Page) -> None:
    """Publish the current OrangeHRM page inside the dashboard."""
    try:
        store.set_preview(
            job_id, page.screenshot(type="png", animations="disabled", timeout=5000)
        )
    except Exception as exc:  # noqa: BLE001 - preview must not stop the workflow
        logger.warning("job=%s preview_error=%s", job_id, type(exc).__name__)


def _id_input(page: Page):
    return (
        page.locator(".oxd-input-group")
        .filter(has=page.locator("label", has_text="Employee Id"))
        .locator("input")
    )


def open_site(page: Page) -> None:
    page.goto(URL, wait_until="domcontentloaded", timeout=30000)
    page.get_by_placeholder("Username").wait_for(state="visible", timeout=20000)


def login(page: Page, data: AutomationInput) -> None:
    page.get_by_placeholder("Username").fill(data.username)
    page.get_by_placeholder("Password").fill(data.password)
    page.get_by_role("button", name="Login").click()
    try:
        page.wait_for_url("**/dashboard/index", timeout=25000)
        page.get_by_role("heading", name="Dashboard").wait_for(
            state="visible", timeout=10000
        )
    except Exception as exc:
        if page.get_by_text("Invalid credentials").is_visible():
            raise AutomationFailure(
                "OrangeHRM rejected the login credentials.",
                "Check the username and password entered in the dashboard. No employee was created.",
            ) from exc
        path = urlparse(page.url).path
        reason = (
            "OrangeHRM stayed on the login page after submission."
            if path.endswith("/auth/login")
            else "OrangeHRM did not finish loading the dashboard after login."
        )
        raise AutomationFailure(
            reason,
            "Check OrangeHRM availability and the entered credentials, then retry. No employee was created.",
        ) from exc


def navigate_pim(page: Page) -> None:
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

    try:
        page.get_by_role("link", name="PIM", exact=True).click(timeout=10000)
        page.get_by_role("heading", name="Employee Information").wait_for(timeout=12000)
    except PlaywrightTimeoutError:
        # Navigation is safe to retry. The demo SPA sometimes leaves the link click
        # on the dashboard even though its PIM route is available.
        page.goto(
            URL + "/web/index.php/pim/viewEmployeeList",
            wait_until="domcontentloaded",
            timeout=30000,
        )
        page.get_by_role("heading", name="Employee Information").wait_for(timeout=20000)
    page.locator(".oxd-table-body .oxd-table-row").first.wait_for(timeout=20000)


def check_duplicate_id(
    page: Page, employee_id: str, on_page: Callable[[], None] | None = None
) -> None:
    """Scan PIM rows before Save; narrow windows collapse the search form."""
    try:
        found = any(
            employee.employee_id == employee_id
            for employee in _collect_employees(
                page, stop_at_id=employee_id, on_page=on_page
            )
        )
    except Exception as exc:
        raise AutomationFailure(
            "Could not finish checking existing employee IDs; nothing was saved.",
            "Wait for the PIM list to load and try again. This run stopped before Save.",
        ) from exc
    if found:
        raise AutomationFailure(
            "Employee ID already exists in OrangeHRM.",
            "Choose a different employee ID. This run stopped before Save.",
        )


def add_employee(
    page: Page, data: AutomationInput, on_page: Callable[[], None] | None = None
) -> None:
    check_duplicate_id(page, data.employee_id, on_page)
    page.get_by_role("button", name="Add").click()
    page.get_by_role("heading", name="Add Employee").wait_for(timeout=15000)
    page.locator('input[name="firstName"]').fill(data.first_name)
    page.locator('input[name="lastName"]').fill(data.last_name)
    _id_input(page).fill(data.employee_id)
    if on_page:
        on_page()
    page.get_by_role("button", name="Save").click()
    try:
        page.wait_for_url("**/pim/viewPersonalDetails/empNumber/*", timeout=18000)
    except Exception as exc:
        if page.get_by_text("Already exists").is_visible():
            raise AutomationFailure(
                "Employee ID already exists in OrangeHRM.",
                "Choose a different employee ID before starting another run.",
            ) from exc
        errors = page.locator(".oxd-input-field-error-message").all_text_contents()
        if errors:
            raise AutomationFailure(
                "OrangeHRM rejected the employee form: " + "; ".join(errors[:3])
            ) from exc
        raise AutomationFailure(
            "Save did not open a saved employee record; creation is uncertain."
        ) from exc


def verify_employee(page: Page, data: AutomationInput) -> Employee:
    from playwright.sync_api import expect

    page.get_by_role("heading", name="Personal Details").wait_for(timeout=15000)
    try:
        expect(_id_input(page)).to_have_value(data.employee_id, timeout=15000)
        expect(page.locator('input[name="firstName"]')).to_have_value(
            data.first_name, timeout=15000
        )
        expect(page.locator('input[name="lastName"]')).to_have_value(
            data.last_name, timeout=15000
        )
    except AssertionError:
        pass  # Read the final saved values below to report a real mismatch.
    employee = Employee(
        employee_id=_id_input(page).input_value().strip(),
        first_name=page.locator('input[name="firstName"]').input_value().strip(),
        last_name=page.locator('input[name="lastName"]').input_value().strip(),
    )
    if (employee.employee_id, employee.first_name, employee.last_name) != (
        data.employee_id,
        data.first_name,
        data.last_name,
    ):
        raise AutomationFailure(
            "Saved employee details do not match the submitted ID and name."
        )
    return employee


def _read_employee_rows(page: Page) -> list[Employee]:
    page.wait_for_function(
        """() => [...document.querySelectorAll('.oxd-table-body .oxd-table-row')]
            .every(row => row.querySelector('.card-header-slot-content')
                ? row.querySelectorAll('.card-body-slot .oxd-table-card-cell .data').length >= 2
                : row.querySelectorAll('[role=cell]').length >= 4)""",
        timeout=10000,
    )
    raw_rows = page.locator(".oxd-table-body .oxd-table-row").evaluate_all(
        """rows => rows.map(row => {
            if (row.querySelector('.card-header-slot-content')) {
                const id = row.querySelector('.card-header-slot-content.--left .data');
                const names = row.querySelectorAll('.card-body-slot .oxd-table-card-cell .data');
                return [id?.innerText.trim() ?? '', names[0]?.innerText.trim(), names[1]?.innerText.trim()];
            }
            const cells = [...row.querySelectorAll('[role=cell]')];
            return [1, 2, 3].map(index => cells[index]?.innerText.trim());
        })"""
    )
    employees: list[Employee] = []
    for cells in raw_rows:
        if len(cells) != 3 or any(value is None for value in cells):
            raise AutomationFailure("Employee list layout changed during extraction.")
        employees.append(
            Employee(
                employee_id=cells[0],
                first_name=cells[1],
                last_name=cells[2],
            )
        )
    return employees


def _collect_employees(
    page: Page,
    stop_at_id: str | None = None,
    on_page: Callable[[], None] | None = None,
) -> list[Employee]:
    employees: list[Employee] = []
    for _ in range(100):
        employees.extend(_read_employee_rows(page))
        if on_page:
            on_page()
        if stop_at_id and any(
            employee.employee_id == stop_at_id for employee in employees
        ):
            return employees
        next_button = page.locator(
            "button.oxd-pagination-page-item--previous-next:has(i.bi-chevron-right)"
        )
        if next_button.count() == 0 or next_button.is_disabled():
            break
        previous = page.locator(".oxd-table-body .oxd-table-row").first.inner_text()
        selected = page.locator(
            "button.oxd-pagination-page-item--page-selected"
        ).inner_text()
        next_button.click()
        page.wait_for_function(
            "old => { const row = document.querySelector('.oxd-table-body .oxd-table-row'); "
            "const selected = document.querySelector('.oxd-pagination-page-item--page-selected'); "
            "return row && selected && selected.innerText.trim() !== old.page && "
            "row.innerText !== old.row && "
            "!document.querySelector('.oxd-loading-spinner'); }",
            arg={"page": selected.strip(), "row": previous},
            timeout=15000,
        )
    else:
        raise AutomationFailure(
            "Employee list has more than 100 pages to export safely."
        )
    if not employees:
        raise AutomationFailure("Employee list contained no readable records.")
    return employees


def extract_employees(
    page: Page, on_page: Callable[[], None] | None = None
) -> list[Employee]:
    page.goto(
        URL + "/web/index.php/pim/viewEmployeeList",
        wait_until="domcontentloaded",
        timeout=30000,
    )
    page.get_by_role("heading", name="Employee Information").wait_for(timeout=20000)
    page.locator(".oxd-table-body .oxd-table-row").first.wait_for(timeout=20000)
    count_text = (
        page.locator(".oxd-text--span")
        .filter(has_text="Records Found")
        .first.inner_text()
    )
    expected_count = re.search(r"\(([\d,]+)\)\s*Records Found", count_text)
    employees = _collect_employees(page, on_page=on_page)
    if expected_count and len(employees) != int(
        expected_count.group(1).replace(",", "")
    ):
        raise AutomationFailure(
            "The employee list changed or was incomplete during extraction.",
            "The saved employee is still verified. Inspect PIM and retry extraction in a new run if needed; no CSV was offered.",
        )
    return employees


def require_employee_in_export(employees: list[Employee], employee_id: str) -> None:
    if not any(employee.employee_id == employee_id for employee in employees):
        raise AutomationFailure(
            "The saved employee ID was missing from the extracted PIM list.",
            "Check PIM for the saved record. The shared demo may have changed during extraction; no CSV was offered for this run.",
        )


def logout(page: Page) -> None:
    page.locator(".oxd-userdropdown-tab").click()
    page.get_by_role("menuitem", name="Logout").click()
    page.get_by_placeholder("Username").wait_for(state="visible", timeout=15000)


def _run_step(
    store: JobStore,
    job_id: str,
    key: str,
    task: Callable,
    message: str,
    after: Callable[[], None] | None = None,
):
    store.step(job_id, key, "running")
    try:
        result = task()
    except AutomationFailure as exc:
        store.step(
            job_id,
            key,
            "failed",
            str(exc),
            exc.next_action or NEXT_ACTIONS[key],
        )
        raise
    except Exception as exc:
        logger.warning(
            "job=%s step=%s exception_type=%s", job_id, key, type(exc).__name__
        )
        safe = {
            "opening": "Could not open the OrangeHRM login page.",
            "login": "Login failed or timed out.",
            "pim": "Could not open the PIM employee list.",
            "creation": "Employee creation failed or is uncertain; check OrangeHRM before retrying.",
            "verification": "Could not verify the saved employee record.",
            "extraction": "Could not extract or export the employee list.",
            "logout": "Could not confirm logout.",
        }[key]
        store.step(job_id, key, "failed", safe, NEXT_ACTIONS[key])
        raise AutomationFailure(safe) from exc
    else:
        store.step(job_id, key, "success", message)
        return result
    finally:
        if after:
            after()


def run_automation(job_id: str, data: AutomationInput, store: JobStore) -> None:
    """Run in FastAPI's background thread. No credentials are stored in JobStore."""
    page = None
    authenticated = False
    error = None
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                context = browser.new_context(viewport={"width": 1100, "height": 760})
                try:
                    page = context.new_page()
                    page.set_default_timeout(15000)
                    capture = lambda: _capture_preview(store, job_id, page)
                    _run_step(
                        store,
                        job_id,
                        "opening",
                        lambda: open_site(page),
                        "Login page ready in dashboard preview",
                        capture,
                    )
                    _run_step(
                        store,
                        job_id,
                        "login",
                        lambda: login(page, data),
                        "Authenticated",
                        capture,
                    )
                    authenticated = True
                    _run_step(
                        store,
                        job_id,
                        "pim",
                        lambda: navigate_pim(page),
                        "PIM opened",
                        capture,
                    )
                    _run_step(
                        store,
                        job_id,
                        "creation",
                        lambda: add_employee(page, data, capture),
                        "Saved record opened",
                        capture,
                    )
                    employee = _run_step(
                        store,
                        job_id,
                        "verification",
                        lambda: verify_employee(page, data),
                        "Saved ID and name match",
                        capture,
                    )
                    store.set_verified(job_id, employee)

                    def extract_and_export() -> list[Employee]:
                        employees = extract_employees(page, capture)
                        require_employee_in_export(employees, data.employee_id)
                        EXPORT_DIR.mkdir(exist_ok=True)
                        target = EXPORT_DIR / f"{job_id}.csv"
                        target.write_text(
                            employees_to_csv(employees), encoding="utf-8", newline=""
                        )
                        return employees

                    employees = _run_step(
                        store,
                        job_id,
                        "extraction",
                        extract_and_export,
                        "Employee list extracted and CSV generated",
                        capture,
                    )
                    store.set_employees(job_id, employees)
                except AutomationFailure as exc:
                    error = str(exc)
                finally:
                    if authenticated and page is not None:
                        try:
                            _run_step(
                                store,
                                job_id,
                                "logout",
                                lambda: logout(page),
                                "Logout confirmed",
                                capture,
                            )
                        except AutomationFailure as exc:
                            error = f"{error} {exc}" if error else str(exc)
                    context.close()
            finally:
                browser.close()
    except Exception as exc:  # noqa: BLE001 - always finalize job on browser or cleanup failure
        logger.warning("job=%s browser_exception_type=%s", job_id, type(exc).__name__)
        opening_pending = store.get(job_id).steps[0].state == "pending"
        error = error or (
            "Browser could not start. Install Playwright Chromium and retry."
            if opening_pending
            else "Browser cleanup failed."
        )
        if opening_pending:
            store.step(
                job_id,
                "opening",
                "failed",
                error,
                "Install Playwright Chromium in the server environment, then retry.",
            )
    finally:
        view = store.get(job_id)
        for key in STEP_NAMES[:-1]:
            if next(step for step in view.steps if step.key == key).state == "pending":
                store.step(job_id, key, "skipped", "Earlier step did not complete")
        failed = bool(error) or any(
            step.state == "failed" for step in store.get(job_id).steps
        )
        store.step(
            job_id, "completed", "failed" if failed else "success", "Workflow finished"
        )
        store.finish(job_id, error)
