#!/bin/sh
set -eu
# Executado SOMENTE no primeiro boot de um volume PostgreSQL vazio.
# Variáveis -v + aspas SQL são necessárias para evitar injeção de credenciais.
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
  --set=postiz_password="$POSTIZ_DB_PASSWORD" --set=temporal_password="$TEMPORAL_DB_PASSWORD" <<'SQL'
CREATE ROLE postiz LOGIN PASSWORD :'postiz_password';
CREATE DATABASE postiz OWNER postiz;
CREATE ROLE temporal LOGIN CREATEDB PASSWORD :'temporal_password';
CREATE DATABASE temporal OWNER temporal;
CREATE DATABASE temporal_visibility OWNER temporal;
SQL
