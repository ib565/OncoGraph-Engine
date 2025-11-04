CREATE TABLE IF NOT EXISTS traces (
    id bigserial PRIMARY KEY,
    run_id text,
    timestamp timestamptz NOT NULL DEFAULT now(),
    step text NOT NULL,
    payload jsonb NOT NULL,
    day date GENERATED ALWAYS AS (timestamp::date) STORED
);

-- Create indexes for faster queries
CREATE INDEX IF NOT EXISTS idx_traces_run_id ON traces(run_id);
CREATE INDEX IF NOT EXISTS idx_traces_step_run_id ON traces(step, run_id);
CREATE INDEX IF NOT EXISTS idx_traces_timestamp ON traces(timestamp DESC);
