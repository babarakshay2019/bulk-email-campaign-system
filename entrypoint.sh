#!/bin/sh
set -e

echo "Running migrations..."
python manage.py migrate --noinput

echo "Starting service..."
exec "$@"
