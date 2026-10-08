-- db_init/02_create_schemas.sql
-- every table lives in the shop schema; put it first on the search_path so
-- unqualified queries (e.g. SQL written by the agent) resolve to it
\c shop
CREATE SCHEMA IF NOT EXISTS shop;
ALTER DATABASE shop SET search_path TO shop, public;
