-- Nagarik Database Schema
-- Run: psql -U your_user -d nagarik_db -f schema.sql

CREATE TABLE IF NOT EXISTS civic_issues (
  id                   SERIAL PRIMARY KEY,
  public_id            VARCHAR(12) UNIQUE NOT NULL,
  title                VARCHAR(255),
  description          TEXT,
  category_id          VARCHAR(50) NOT NULL,
  dept                 VARCHAR(100),
  ai_confidence        FLOAT,
  city_id              VARCHAR(50) NOT NULL,
  ward                 VARCHAR(100),
  address              TEXT,
  geo_lat              DECIMAL(10,7),
  geo_lng              DECIMAL(10,7),
  status               VARCHAR(20) DEFAULT 'open',
  escalation_level     VARCHAR(5)  DEFAULT 'L1',
  escalation_role      VARCHAR(100),
  urgency_score        INTEGER DEFAULT 0,
  duplicate_cluster    VARCHAR(50),
  duplicate_count      INTEGER DEFAULT 0,
  upvote_count         INTEGER DEFAULT 0,
  photo_urls           TEXT[],
  proof_photo_url      TEXT,
  reporter_hash        VARCHAR(64),
  reporter_phone_enc   TEXT,
  source               VARCHAR(20) DEFAULT 'app',
  resolved_at          TIMESTAMP,
  resolution_remarks   TEXT,
  citizen_confirmed    BOOLEAN,
  citizen_confirmed_at TIMESTAMP,
  created_at           TIMESTAMP DEFAULT NOW(),
  updated_at           TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS escalation_logs (
  id           SERIAL PRIMARY KEY,
  issue_id     INTEGER REFERENCES civic_issues(id),
  from_level   VARCHAR(5),
  to_level     VARCHAR(5),
  to_role      VARCHAR(100),
  reason       TEXT,
  escalated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS issue_upvotes (
  id         SERIAL PRIMARY KEY,
  issue_id   INTEGER REFERENCES civic_issues(id),
  voter_hash VARCHAR(64),
  created_at TIMESTAMP DEFAULT NOW(),
  UNIQUE(issue_id, voter_hash)
);

CREATE TABLE IF NOT EXISTS civic_polls (
  id          SERIAL PRIMARY KEY,
  title       VARCHAR(255) NOT NULL,
  description TEXT,
  city_id     VARCHAR(50),
  ward        VARCHAR(100),
  created_by  INTEGER,
  ends_at     TIMESTAMP,
  status      VARCHAR(20) DEFAULT 'active',
  created_at  TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS poll_options (
  id      SERIAL PRIMARY KEY,
  poll_id INTEGER REFERENCES civic_polls(id),
  text    VARCHAR(255) NOT NULL,
  votes   INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS poll_votes (
  id         SERIAL PRIMARY KEY,
  poll_id    INTEGER REFERENCES civic_polls(id),
  option_id  INTEGER REFERENCES poll_options(id),
  voter_hash VARCHAR(64),
  created_at TIMESTAMP DEFAULT NOW(),
  UNIQUE(poll_id, voter_hash)
);

CREATE TABLE IF NOT EXISTS civic_health_scores (
  id                   SERIAL PRIMARY KEY,
  city_id              VARCHAR(50),
  ward                 VARCHAR(100),
  score                INTEGER,
  resolution_rate      FLOAT,
  repeat_issue_rate    FLOAT,
  avg_resolution_hours FLOAT,
  computed_at          TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS cities (
  id            VARCHAR(50) PRIMARY KEY,
  name          VARCHAR(100) NOT NULL,
  state         VARCHAR(100),
  custom_domain VARCHAR(255),
  logo_url      TEXT,
  primary_color VARCHAR(10) DEFAULT '#F5A623',
  active        BOOLEAN DEFAULT TRUE,
  created_at    TIMESTAMP DEFAULT NOW()
);
