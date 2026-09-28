"""Reference data: the instruments and departments named in SPEC 11."""

INSTRUMENTS = [
    # (name as it appears in the source data, short code, citation, description)
    ("TSP Licence", "LIC", "NERC/LC/104", "Transmission Service Provider licence issued by NERC."),
    ("Eligible Customer Regulations 2024", "ECR", "", "NERC Eligible Customer Regulations."),
    (
        "Grid Code v03 (2018)",
        "GC",
        "",
        "The Grid Code for the Nigeria Electricity Supply Industry.",
    ),
    ("Market Rules 2014", "MR", "", "Market Rules for the Transitional and Medium Term Stages."),
    ("Nigeria Electricity H&S Code 2014", "HSC", "", "Nigeria Electricity Health and Safety Code."),
    (
        "NESIS Regulations 2015",
        "NESIS",
        "",
        "Nigerian Electricity Supply and Installation Standards Regulations.",
    ),
    ("Electricity Act 2023", "EA", "", "The Electricity Act 2023."),
    (
        "All Regulatory Instruments",
        "GEN",
        "",
        "Cross-cutting obligations that apply to several instruments.",
    ),
]

DEPARTMENTS = [
    ("Regulation & Compliance", "RC"),
    ("Corporate Planning", "CP"),
    ("Legal", "LEGAL"),
    ("Transmission Services", "TS"),
    ("Finance & Accounts", "FIN"),
    ("Business Development/TUoS", "BD"),
    ("Risk Management", "RISK"),
    ("Admin & Corporate Services", "ACS"),
    ("Procurement", "PROC"),
    ("Material Control & Stores", "MCS"),
    ("HSE", "HSE"),
    ("Corporate Security Services", "CSS"),
    ("ICT", "ICT"),
    ("System Planning & Development", "SPD"),
    ("Protection, Control & Metering", "PCM"),
    ("Engineering", "ENG"),
    ("Treasury Management Services", "TMS"),
    ("Industrial Relations", "IR"),
    ("All Regions (10 Regional GMs)", "REGIONS"),
    ("Monitoring & Evaluation", "ME"),
]

# Abbreviations used in the source data's "supporting" column for existing departments.
DEPARTMENT_ALIASES = {
    "PC&M": "Protection, Control & Metering",
    "TS": "Transmission Services",
    "SP&D": "System Planning & Development",
    "CSSD": "Corporate Security Services",
    "All Regions": "All Regions (10 Regional GMs)",
}

# Markers in the supporting column that are not departments.
NOT_A_DEPARTMENT = {"All Departments"}
