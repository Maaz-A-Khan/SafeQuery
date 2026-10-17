-- The read-only account the agent connects to Chinook with. Run in `chinook` as a superuser.
-- Variables: ro_user, ro_password. Safe to re-run; re-run after reloading Chinook.

SELECT format('CREATE ROLE %I LOGIN', :'ro_user')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = :'ro_user') \gexec

ALTER ROLE :"ro_user" WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION
    PASSWORD :'ro_password';

-- Every session starts read-only even before the app sets it.
ALTER ROLE :"ro_user" SET default_transaction_read_only = on;

GRANT CONNECT ON DATABASE chinook TO :"ro_user";
GRANT USAGE ON SCHEMA public TO :"ro_user";
GRANT SELECT ON ALL TABLES IN SCHEMA public TO :"ro_user";
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
