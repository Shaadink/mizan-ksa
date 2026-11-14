# Airflow 2.10 (OpenLineage provider included) + DuckDB for the freshness and residency gates on the mounted lake.
FROM apache/airflow:2.10.5-python3.12
RUN pip install --no-cache-dir duckdb==2.0.0
ENV PYTHONPATH=/opt/mizan/src MIZAN_REPO=/opt/mizan MIZAN_LAKE_ROOT=/opt/mizan/data/lake
