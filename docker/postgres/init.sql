-- ============================================================
-- init.sql — Initialisation PostgreSQL — Mobilité Durable
-- Exécuté automatiquement au premier démarrage du conteneur
-- ============================================================

-- Extensions utiles
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_stat_statements";

-- Paramètres de performance minimaux pour le pipeline
ALTER SYSTEM SET work_mem = '16MB';
ALTER SYSTEM SET checkpoint_completion_target = '0.9';

-- Confirmation
SELECT 'mobilite_durable database initialized' AS status;
