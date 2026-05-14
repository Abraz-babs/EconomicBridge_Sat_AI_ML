-- init_db.sql — EconomicBridge PostgreSQL Initialization
-- ======================================================
-- Runs automatically on first `docker-compose up postgres`.
-- Creates required extensions and the application database user.

-- Extensions (require superuser on first create)
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "postgis";
CREATE EXTENSION IF NOT EXISTS "hstore";

-- TimescaleDB may not be available in the postgis image — skip gracefully
DO $$
BEGIN
    CREATE EXTENSION IF NOT EXISTS "timescaledb" CASCADE;
EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'TimescaleDB extension not available — skipping. Install for production.';
END
$$;

-- Create application user with limited privileges
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'economicbridge_app') THEN
        CREATE ROLE economicbridge_app WITH LOGIN PASSWORD 'devpassword';
    END IF;
END
$$;

-- Grant connect privilege
GRANT CONNECT ON DATABASE economicbridge TO economicbridge_app;
GRANT USAGE ON SCHEMA public TO economicbridge_app;

-- The application user should NOT have DELETE on audit tables.
-- Specific table-level grants are applied per-schema by the migration scripts.

-- Log completion
DO $$
BEGIN
    RAISE NOTICE 'EconomicBridge database initialized successfully.';
END
$$;
