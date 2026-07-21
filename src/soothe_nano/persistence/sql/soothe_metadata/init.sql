-- soothe_metadata: nano-owned namespace-isolated JSONB key-value persistence
-- (soothe_persistence KV + migrations only).
-- Host/daemon-only tables are NOT created here:
--   cron_jobs, identity_*  -> applied at runtime by the host
--   display_card_mutations, goal_display_snapshots
--                           -> applied by the daemon display store (IG-678 PR-2)
-- A standalone nano never reads or writes any of those.

CREATE TABLE IF NOT EXISTS soothe_schema_migrations (
    version TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS soothe_persistence (
    key TEXT NOT NULL,
    namespace TEXT NOT NULL,
    data JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (namespace, key)
);

CREATE INDEX IF NOT EXISTS idx_persistence_updated
    ON soothe_persistence(updated_at);
