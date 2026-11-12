"""MIZAN-KSA: Saudi regulated commerce & payments data integrity platform."""

__version__ = "0.1.0"

SPEC_REVISION = "v1.1 - Design Freeze"
TIMEZONE = "Asia/Riyadh"

# The 9 namespaces (spec Section 7). Frozen.
LAKEHOUSE = "LH_MIZAN"
WAREHOUSE = "WH_MIZAN"
LAKEHOUSE_SCHEMAS = ("brz", "ctl", "slv", "quarantine", "security", "audit", "meta", "ai")
WAREHOUSE_SCHEMAS = ("gld",)
