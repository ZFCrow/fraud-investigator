#!/bin/sh
# Loads the synthetic store data once. seed.sql starts by truncating the store tables,
# so it is only run when they are still empty -- a restart must not reset the data.
set -eu

export PGPASSWORD="$DB_PASSWORD"
PSQL="psql -v ON_ERROR_STOP=1 -h $DB_HOST -p $DB_PORT -U $DB_USER -d $DB_NAME"

customers=$($PSQL -tAc "select count(*) from shop.customers")
if [ "$customers" != "0" ]; then
    echo "seed: store data already loaded ($customers customers), nothing to do"
    exit 0
fi

echo "seed: loading /seed/seed.sql"
$PSQL -q -f /seed/seed.sql
echo "seed: done ($($PSQL -tAc 'select count(*) from shop.customers') customers)"
