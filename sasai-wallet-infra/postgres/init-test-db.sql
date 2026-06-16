-- Sasai Wallet — Postgres init script
--
-- Runs ONCE on the first start of the container (postgres-data volume
-- empty). Creates the parallel test database used by pytest. Both DBs
-- share the same `wallet` role and password as the main one — sufficient
-- for local dev.

CREATE DATABASE wallet_platform_test
  WITH OWNER = wallet
       ENCODING = 'UTF8';

-- pgcrypto is what our migrations call for `gen_random_uuid()`. Loading
-- it here avoids a manual `CREATE EXTENSION` step per fresh container.
\connect wallet_platform;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

\connect wallet_platform_test;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
