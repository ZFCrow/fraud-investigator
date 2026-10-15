-- db_init/04_grant_schema.sql
\c shop
GRANT ALL ON SCHEMA shop TO shop;
ALTER DEFAULT PRIVILEGES IN SCHEMA shop GRANT ALL ON TABLES TO shop;
ALTER DEFAULT PRIVILEGES IN SCHEMA shop GRANT ALL ON SEQUENCES TO shop;
-- the agent's read-only role may look inside the schema; which tables it can read is
-- granted by migration b2d4f6a8c0e1
GRANT USAGE ON SCHEMA shop TO shop_reader;
