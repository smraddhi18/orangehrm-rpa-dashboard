"""API, job state, validation, and CSV behavior without external side effects."""

import csv
from io import StringIO

from fastapi.testclient import TestClient

from app.main import create_app
from app.schemas import Employee
from app.services import automation
from app.services.automation import (
    AutomationFailure,
    _capture_preview,
    _run_step,
    require_employee_in_export,
)
from app.services.employee_export import employees_to_csv

PAYLOAD = {
    "username": " Admin ",
    "password": "test-password",
    "first_name": " Maya ",
    "last_name": " Shah ",
    "employee_id": " A12345 ",
}


def success_runner(job_id, data, store):
    assert data.username == "Admin"
    assert data.first_name == "Maya"
    employee = Employee(
        employee_id=data.employee_id,
        first_name=data.first_name,
        last_name=data.last_name,
    )
    for key in (
        "opening",
        "login",
        "pim",
        "creation",
        "verification",
        "extraction",
        "logout",
        "completed",
    ):
        store.step(job_id, key, "success", "Confirmed")
        if key == "verification":
            store.set_verified(job_id, employee)
        if key == "extraction":
            store.set_employees(job_id, [employee])
    store.finish(job_id)


def test_success_flow_and_export():
    client = TestClient(create_app(success_runner))
    response = client.post("/api/automation/run", json=PAYLOAD)
    assert response.status_code == 202
    job_id = response.json()["job_id"]
    status = client.get(f"/api/automation/{job_id}/status")
    assert status.status_code == 200
    body = status.json()
    assert body["status"] == "success"
    assert body["verified_employee"] == {
        "employee_id": "A12345",
        "first_name": "Maya",
        "last_name": "Shah",
    }
    assert body["extracted_count"] == 1
    assert all(step["state"] == "success" for step in body["steps"])
    exported = client.get(f"/api/automation/{job_id}/export")
    assert exported.status_code == 200
    rows = list(csv.reader(StringIO(exported.content.decode("utf-8-sig"))))
    assert rows == [
        ["Employee ID", "First Name", "Last Name"],
        ["A12345", "Maya", "Shah"],
    ]


def test_validation_rejects_missing_and_blank_fields():
    client = TestClient(create_app(success_runner))
    assert client.post("/api/automation/run", json={}).status_code == 422
    assert (
        client.post(
            "/api/automation/run", json={**PAYLOAD, "first_name": "   "}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/automation/run", json={**PAYLOAD, "password": "   "}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/automation/run", json={**PAYLOAD, "employee_id": "x" * 11}
        ).status_code
        == 422
    )


def test_unknown_job_and_unready_export():
    def unfinished_runner(job_id, data, store):
        store.step(job_id, "opening", "failed", "Connection failed")
        store.finish(job_id, "Connection failed")

    client = TestClient(create_app(unfinished_runner))
    assert client.get("/api/automation/missing/status").status_code == 404
    job_id = client.post("/api/automation/run", json=PAYLOAD).json()["job_id"]
    assert client.get(f"/api/automation/{job_id}/export").status_code == 409
    assert client.get(f"/api/automation/{job_id}/preview").status_code == 409
    assert client.get(f"/api/automation/{job_id}/status").json()["status"] == "failed"


def test_creation_success_with_later_failure_is_partial():
    def partial_runner(job_id, data, store):
        store.step(job_id, "verification", "success", "Saved record checked")
        store.set_verified(
            job_id, Employee(employee_id="A12345", first_name="Maya", last_name="Shah")
        )
        store.step(job_id, "extraction", "failed", "Could not extract list")
        store.finish(job_id, "Could not extract list")

    client = TestClient(create_app(partial_runner))
    job_id = client.post("/api/automation/run", json=PAYLOAD).json()["job_id"]
    body = client.get(f"/api/automation/{job_id}/status").json()
    assert body["status"] == "partial"
    assert body["verified_employee"]["employee_id"] == "A12345"
    assert not body["export_ready"]


def test_concurrent_job_rejected():
    app = create_app(success_runner)
    assert app.state.jobs.create() is not None
    response = TestClient(app).post("/api/automation/run", json=PAYLOAD)
    assert response.status_code == 409


def test_preview_endpoint_returns_current_frame():
    image = b"\x89PNG\r\n\x1a\nframe"

    def runner(job_id, data, store):
        store.set_preview(job_id, image)
        store.finish(job_id)

    client = TestClient(create_app(runner))
    assert client.get("/api/automation/missing/preview").status_code == 404
    job_id = client.post("/api/automation/run", json=PAYLOAD).json()["job_id"]
    status = client.get(f"/api/automation/{job_id}/status").json()
    assert status["preview_version"] == 1
    response = client.get(f"/api/automation/{job_id}/preview")
    assert response.status_code == 200
    assert response.content == image
    assert response.headers["content-type"] == "image/png"


def test_csv_handles_commas_quotes_and_unicode():
    text = employees_to_csv(
        [Employee(employee_id="X,1", first_name='Ana "A"', last_name="Émile")]
    )
    rows = list(csv.reader(StringIO(text.lstrip("\ufeff"))))
    assert rows[1] == ["X,1", 'Ana "A"', "Émile"]


def test_credentials_are_absent_from_job_state():
    client = TestClient(create_app(success_runner))
    job_id = client.post("/api/automation/run", json=PAYLOAD).json()["job_id"]
    serialized = client.get(f"/api/automation/{job_id}/status").text
    assert "test-password" not in serialized
    assert "username" not in serialized


def test_failure_reason_and_next_action_are_kept_per_step():
    from app.jobs import JobStore

    store = JobStore()
    job_id = store.create().job_id

    def fail():
        raise AutomationFailure(
            "Employee ID already exists in OrangeHRM.", "Choose another ID."
        )

    import pytest

    with pytest.raises(AutomationFailure):
        _run_step(store, job_id, "creation", fail, "Saved")
    step = next(step for step in store.get(job_id).steps if step.key == "creation")
    assert step.message == "Employee ID already exists in OrangeHRM."
    assert step.next_action == "Choose another ID."


def test_page_capture_updates_preview_without_exposing_image_in_status():
    from app.jobs import JobStore

    class Page:
        def screenshot(self, **kwargs):
            assert kwargs["type"] == "png"
            return b"frame"

    store = JobStore()
    job_id = store.create().job_id
    _capture_preview(store, job_id, Page())
    assert store.get(job_id).preview_version == 1
    assert store.get_preview(job_id) == b"frame"
    assert "frame" not in store.get(job_id).model_dump_json()


def test_pagination_continues_past_five_visible_page_buttons(monkeypatch):
    class Locator:
        def __init__(self, page, kind):
            self.page = page
            self.kind = kind

        def count(self):
            return int(self.page.number < 8)

        def is_disabled(self):
            return False

        def click(self):
            self.page.number += 1

        @property
        def first(self):
            return self

        def inner_text(self):
            return (
                str(self.page.number)
                if self.kind == "selected"
                else f"row-{self.page.number}"
            )

    class Page:
        def __init__(self):
            self.number = 1

        def locator(self, selector):
            if "previous-next" in selector:
                return Locator(self, "next")
            if "page-selected" in selector:
                return Locator(self, "selected")
            return Locator(self, "row")

        def wait_for_function(self, expression, arg, timeout):
            assert arg == {
                "page": str(self.number - 1),
                "row": f"row-{self.number - 1}",
            }

    monkeypatch.setattr(
        automation,
        "_read_employee_rows",
        lambda page: [
            Employee(
                employee_id=f"E{page.number}", first_name="Test", last_name="Person"
            )
        ],
    )
    assert [row.employee_id for row in automation._collect_employees(Page())] == [
        f"E{number}" for number in range(1, 9)
    ]
    assert [
        row.employee_id
        for row in automation._collect_employees(Page(), stop_at_id="E7")
    ] == [f"E{number}" for number in range(1, 8)]


def test_export_requires_the_verified_employee_id():
    import pytest

    employees = [Employee(employee_id="OTHER1", first_name="A", last_name="B")]
    with pytest.raises(AutomationFailure, match="missing from the extracted"):
        require_employee_in_export(employees, "NEW123")
    require_employee_in_export(employees, "OTHER1")


def test_extraction_rejects_a_truncated_list(monkeypatch):
    import pytest

    class Locator:
        @property
        def first(self):
            return self

        def filter(self, **kwargs):
            return self

        def wait_for(self, **kwargs):
            pass

        def inner_text(self):
            return "(3) Records Found"

    class Page:
        def goto(self, *args, **kwargs):
            pass

        def get_by_role(self, *args, **kwargs):
            return Locator()

        def locator(self, *args, **kwargs):
            return Locator()

    monkeypatch.setattr(
        automation,
        "_collect_employees",
        lambda page, on_page: [
            Employee(employee_id="E1", first_name="A", last_name="B"),
            Employee(employee_id="E2", first_name="C", last_name="D"),
        ],
    )
    with pytest.raises(AutomationFailure, match="incomplete during extraction"):
        automation.extract_employees(Page())
