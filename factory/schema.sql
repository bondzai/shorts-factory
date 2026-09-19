CREATE TABLE IF NOT EXISTS clips (
    id              TEXT PRIMARY KEY,
    created_at      TEXT NOT NULL,
    generator       TEXT NOT NULL,
    variant         TEXT,
    seed            INTEGER NOT NULL,
    params_json     TEXT NOT NULL,
    hook            TEXT,
    plan_why        TEXT,
    status          TEXT NOT NULL,
    video_path      TEXT,
    render_desc     TEXT,
    facts_json      TEXT,
    duration_s      REAL,
    width           INTEGER,
    height          INTEGER,
    fps             REAL,
    loudness_lufs   REAL,
    phash           TEXT,
    sameness        REAL,
    title           TEXT,
    description     TEXT,
    hashtags_json   TEXT,
    qc_json         TEXT,
    reject_reason   TEXT,
    platform        TEXT,
    remote_id       TEXT,
    published_at    TEXT,
    views           INTEGER,
    avg_view_pct    REAL,
    swipe_away_pct  REAL,
    likes           INTEGER,
    metrics_at      TEXT,
    cost_usd        REAL NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS clips_status ON clips (status);
CREATE INDEX IF NOT EXISTS clips_published ON clips (published_at);

CREATE TABLE IF NOT EXISTS digests (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at    TEXT NOT NULL,
    n_published   INTEGER NOT NULL,
    body          TEXT NOT NULL,
    rules_applied INTEGER NOT NULL DEFAULT 0
);
