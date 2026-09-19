CREATE TABLE IF NOT EXISTS channels (
    id            TEXT PRIMARY KEY,
    created_at    TEXT NOT NULL,
    name          TEXT NOT NULL,
    handle        TEXT,
    platform      TEXT NOT NULL DEFAULT 'youtube',
    driver        TEXT NOT NULL DEFAULT 'manual',
    variants_json TEXT NOT NULL DEFAULT '[]',
    cadence       INTEGER NOT NULL DEFAULT 1,
    active        INTEGER NOT NULL DEFAULT 1,
    note          TEXT
);

CREATE TABLE IF NOT EXISTS clips (
    id              TEXT PRIMARY KEY,
    channel_id      TEXT NOT NULL DEFAULT 'main' REFERENCES channels (id),
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
    purged_at       TEXT,
    cost_usd        REAL NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS clips_status ON clips (channel_id, status);
CREATE INDEX IF NOT EXISTS clips_published ON clips (channel_id, published_at);

CREATE TABLE IF NOT EXISTS digests (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id     TEXT NOT NULL DEFAULT 'main' REFERENCES channels (id),
    created_at     TEXT NOT NULL,
    n_published    INTEGER NOT NULL,
    body           TEXT NOT NULL,
    proposals_json TEXT NOT NULL DEFAULT '[]',
    rules_applied  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id  TEXT NOT NULL DEFAULT 'main' REFERENCES channels (id),
    started_at  TEXT NOT NULL,
    ended_at    TEXT,
    kind        TEXT NOT NULL,
    status      TEXT NOT NULL,
    detail      TEXT,
    log         TEXT,
    cost_usd    REAL NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS runs_recent ON runs (channel_id, started_at DESC);
