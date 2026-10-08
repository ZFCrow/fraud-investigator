#!/bin/sh
# db_init/03_create_users.sh
#
# app/migration user with access to the shop db. Its password comes from
# APP_DB_PASSWORD in .env.db (must match DB_PASSWORD in .env), so a deployment does
# not run with a password that is published in this repo. Unset, it falls back to the
# local-dev default that migrations/alembic.ini also uses.
set -eu

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
     -v app_password="${APP_DB_PASSWORD:-shop_dev}" <<'EOSQL'
CREATE USER shop WITH PASSWORD :'app_password';
GRANT ALL PRIVILEGES ON DATABASE shop TO shop;
EOSQL
