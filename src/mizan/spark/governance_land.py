"""Module 6 in the lakehouse: catalog every LH_MIZAN column into meta.column_classification (NDMO 4 tiers)."""

from __future__ import annotations

from mizan import LAKEHOUSE_SCHEMAS
from mizan.governance.catalog import build_catalog, over_classification
from mizan.spark.lake import Lake, rows_to_df

CATALOG_COLS = ["schema_name", "table_name", "column_name", "data_type", "classification", "rule_id",
                "is_personal_data", "table_classification", "is_over_classified", "subject_key", "legal_hold_class",
                "catalog_version"]


def lake_tables(lake: Lake) -> dict[str, list[tuple[str, str]]]:
    out = {}
    for schema in LAKEHOUSE_SCHEMAS:
        if schema == "meta":
            continue                       # the catalog does not catalog itself
        for t in lake.list_tables(schema):
            out[f"{schema}.{t}"] = [(f.name, f.dataType.simpleString()) for f in lake.read(schema, t).schema.fields]
    return out


def run_governance(lake: Lake) -> dict:
    rows = build_catalog(lake_tables(lake))          # raises on an unmapped table or unknown class (fail closed)
    lake.write(rows_to_df(lake.spark, CATALOG_COLS, rows, {"is_personal_data": "boolean",
                                                           "is_over_classified": "boolean"}),
               "meta", "column_classification", "overwrite", overwrite_schema=True, constraints={
                   "tier_enum": "classification IN ('PUBLIC', 'CONFIDENTIAL', 'SECRET', 'TOP_SECRET')",
                   "hold_enum": "legal_hold_class IN ('TAX', 'SAMA', 'CONSENT')"})
    oc = over_classification(rows)
    return {"columns": len(rows), "tables": len(oc),
            "secret_or_higher_tables": sum(1 for t in oc if t["table_classification"] in ("SECRET", "TOP_SECRET")),
            "over_classified_columns": sum(t["over_classified_columns"] for t in oc)}
