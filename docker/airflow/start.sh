#!/usr/bin/env bash
# Airflow container entry: migrate, create the admin user from the git-ignored .env, run scheduler + webserver.
set -euo pipefail
if [ -z "${AIRFLOW_ADMIN_PASSWORD:-}" ]; then
  echo "AIRFLOW_ADMIN_PASSWORD is not set (put it in .env; scripts/init_local_env.py writes one)" >&2
  exit 1
fi
airflow db migrate
airflow users create --role Admin --username admin --firstname MIZAN --lastname Admin \
  --email admin@example.com --password "${AIRFLOW_ADMIN_PASSWORD}" || true
airflow scheduler &
exec airflow webserver
