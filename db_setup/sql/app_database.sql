-- The app's own database and account (NFR-S5). Run as a PostgreSQL superuser.
-- Variables: app_user, app_password, app_db. CREATEDB lets pytest create its test database.

SELECT format('CREATE ROLE %I LOGIN', :'app_user')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = :'app_user') \gexec

ALTER ROLE :"app_user" WITH LOGIN CREATEDB PASSWORD :'app_password';

SELECT format('CREATE DATABASE %I OWNER %I', :'app_db', :'app_user')
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = :'app_db') \gexec
