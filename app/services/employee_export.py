"""CSV output for extracted records."""

import csv
from io import StringIO

from app.schemas import Employee


def employees_to_csv(employees: list[Employee]) -> str:
    output = StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(("Employee ID", "First Name", "Last Name"))
    for employee in employees:
        writer.writerow((employee.employee_id, employee.first_name, employee.last_name))
    return "\ufeff" + output.getvalue()
