-- Run Ledger Schema and Initial Seed Migration
CREATE TABLE IF NOT EXISTS runs (
    run_id VARCHAR(128) PRIMARY KEY,
    sandbox_name VARCHAR(128) NOT NULL,
    problem_id VARCHAR(128) NOT NULL,
    state VARCHAR(32) NOT NULL,
    execution_target VARCHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Seed row for initial test and verification
-- Re-running this script must not duplicate the seed row
INSERT INTO runs (run_id, sandbox_name, problem_id, state, execution_target, created_at, updated_at)
VALUES (
    'run-seed0001',
    'sbx-seeddemo1',
    'issue-repro-seed-problem',
    'deleted',
    'celesto_sandbox',
    NOW(),
    NOW()
)
ON CONFLICT (run_id) DO UPDATE SET
    sandbox_name = EXCLUDED.sandbox_name,
    problem_id = EXCLUDED.problem_id,
    state = EXCLUDED.state,
    execution_target = EXCLUDED.execution_target,
    updated_at = NOW();
