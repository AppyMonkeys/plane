#!/bin/bash
set -e

python manage.py wait_for_db
# Wait for migrations
python manage.py wait_for_migrations
# Run the processes
# CELERY_CONCURRENCY caps the prefork pool (default: one process per CPU)
celery -A plane worker -l info ${CELERY_CONCURRENCY:+--concurrency="$CELERY_CONCURRENCY"}