def good_submission(**over) -> dict:
    data = {
        "compliance_status": "COMPLIANT",
        "evidence_available": "YES",
        "evidence_description": "Annual report attached.",
    }
    data.update(over)
    return data
