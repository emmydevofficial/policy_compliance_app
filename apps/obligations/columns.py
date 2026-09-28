"""The client's workbook column order (SPEC 10). The exporter writes exactly these headers in
exactly this order, and the importer reads them. Anything downstream depends on it."""

REGISTER_COLUMNS: list[tuple[str, str]] = [
    ("Obligation ID", "id"),
    ("Regulatory Source", "source"),
    ("Document Reference", "ref"),
    ("Obligation Category", "category"),
    ("Obligation Description", "description"),
    ("Obligation Type", "type"),
    ("Frequency", "frequency"),
    ("Primary Responsible Dept", "dept"),
    ("Supporting Departments", "supporting"),
    ("Risk Level", "risk"),
    ("Evidence / Documentation Required", "evidence"),
    ("Regulatory Deadline / Trigger", "deadline"),
    ("Notes / Penalty for Non-Compliance", "notes"),
]
REGISTER_HEADERS = [h for h, _ in REGISTER_COLUMNS]
