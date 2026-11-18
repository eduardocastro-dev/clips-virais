#!/bin/sh
set -eu
# psql variables quote literals safely; each app gets its own role/database.
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
  --set=postiz_password="$POSTIZ_DB_PASSWORD" --set=temporal_password="$TEMPORAL_DB_PASSWORD" <<'SQL'
CREATE ROLE postiz LOGIN PASSWORD :'postiz_password';
CREATE DATABASE postiz OWNER postiz;
CREATE ROLE temporal LOGIN CREATEDB PASSWORD :'temporal_password';
CREATE DATABASE temporal OWNER temporal;
SQL
