-- Run this in your Supabase SQL editor to set up the schema

CREATE TABLE IF NOT EXISTS listings (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  external_id     TEXT NOT NULL,
  source          TEXT NOT NULL,  -- 'housinganywhere' | 'idealista' | 'spotahome' | 'fotocasa'
  url             TEXT NOT NULL,
  title           TEXT,
  price_eur       INTEGER,
  area_m2         INTEGER,
  neighborhood    TEXT,
  address         TEXT,
  furnished       BOOLEAN DEFAULT TRUE,
  available_from  DATE,
  description     TEXT,
  images          TEXT[] DEFAULT '{}',
  lat             DOUBLE PRECISION,
  lng             DOUBLE PRECISION,
  raw_data        JSONB DEFAULT '{}',
  first_seen_at   TIMESTAMPTZ DEFAULT NOW(),
  last_seen_at    TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(source, external_id)
);

CREATE TABLE IF NOT EXISTS ratings (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  listing_id  UUID REFERENCES listings(id) ON DELETE CASCADE,
  rating      TEXT CHECK (rating IN ('good', 'bad', 'maybe')),
  comment     TEXT,
  created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- Let the dashboard read listings and write ratings without auth
ALTER TABLE listings ENABLE ROW LEVEL SECURITY;
ALTER TABLE ratings  ENABLE ROW LEVEL SECURITY;

CREATE POLICY "public read listings"  ON listings FOR SELECT USING (true);
CREATE POLICY "public read ratings"   ON ratings  FOR SELECT USING (true);
CREATE POLICY "public insert ratings" ON ratings  FOR INSERT WITH CHECK (true);
