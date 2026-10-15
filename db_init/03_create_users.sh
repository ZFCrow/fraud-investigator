#!/bin/sh
# db_init/03_create_users.sh
#
# app/migration user with access to the shop db. Its password comes from
# APP_DB_PASSWORD in .env.db (must match DB_PASSWORD in .env), so a deployment does
# not run with a password that is published in this repo. Unset, it falls back to the
# local-dev default that migrations/alembic.ini also uses.
#
# shop_reader is the role the agent's own SQL runs as (DB_READER_USER / DB_READER_PASSWORD
# in .env, password from READER_DB_PASSWORD in .env.db). It can connect and nothing more
# here; SELECT on the store tables is granted by a migration once the tables exist. Its
# sessions are read-only and a statement is cancelled after 15 s.
set -eu

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
     -v app_password="${APP_DB_PASSWORD:-shop_dev}" \
     -v reader_password="${READER_DB_PASSWORD:-shop_reader_dev}" <<'EOSQL'
CREATE USER shop WITH PASSWORD :'app_password';
GRANT ALL PRIVILEGES ON DATABASE shop TO shop;

CREATE USER shop_reader WITH PASSWORD :'reader_password';
GRANT CONNECT ON DATABASE shop TO shop_reader;
ALTER ROLE shop_reader SET default_transaction_read_only = on;
ALTER ROLE shop_reader SET statement_timeout = '15s';
EOSQL
