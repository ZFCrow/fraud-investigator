# Postgres with this project's init scripts and synthetic seed data baked in, so a
# deployment needs no files from the repo.
#
# - the init scripts run by themselves the first time the data volume is created
#   (database, schema, app user)
# - seed.sh is what the one-shot `seed` service runs (see docker-compose.prod.yml)
FROM postgres:15

COPY ./db_init/*.sql ./db_init/*.sh /docker-entrypoint-initdb.d/
RUN chmod +x /docker-entrypoint-initdb.d/*.sh
COPY ./data/synthetic/seed.sql /seed/seed.sql
COPY ./data/synthetic/seed.sh /seed/seed.sh
RUN chmod +x /seed/seed.sh
