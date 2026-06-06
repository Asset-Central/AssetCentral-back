-- =============================================================================
-- Hybrid Search RPC: search_assets_hybrid_rrf
--
-- Combines two retrieval legs with Reciprocal Rank Fusion (k = 60):
--   Leg 1 — BM25 full-text via tsvector / websearch_to_tsquery('simple')
--            + trigram fallback (pg_trgm) when BM25 returns no rows
--   Leg 2 — Cosine vector similarity (pgvector <=> operator)
--            Only active when query_embedding IS NOT NULL.
--
-- The caller (MCP Edge Function) optionally pre-computes the embedding
-- via OpenAI text-embedding-3-small and passes it in. When no embedding
-- is provided the function degrades gracefully to BM25 + trigram only.
-- =============================================================================

-- pg_trgm: required for similarity() fallback
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- GIN index — accelerates @@ operator on search_vector
CREATE INDEX IF NOT EXISTS idx_assets_search_vector_gin
  ON public.assets USING GIN (search_vector);

-- GIN index — accelerates similarity() / % operator on ticker+name
CREATE INDEX IF NOT EXISTS idx_assets_trgm_gin
  ON public.assets USING GIN (
    (lower(ticker) || ' ' || lower(COALESCE(external_name, '')))
    gin_trgm_ops
  );

-- HNSW index — accelerates <=> approximate nearest-neighbor on embeddings
-- (safe to create on a table with no embeddings yet; will be used once
--  rows with non-NULL embeddings exist)
CREATE INDEX IF NOT EXISTS idx_assets_embedding_hnsw
  ON public.assets USING hnsw (embedding extensions.vector_cosine_ops)
  WITH (m = 16, ef_construction = 64);

-- Drop any prior signature so we can change parameter types cleanly
DROP FUNCTION IF EXISTS public.search_assets_hybrid_rrf(text, extensions.vector, int, int);
DROP FUNCTION IF EXISTS public.search_assets_hybrid_rrf(text, int, int);

CREATE OR REPLACE FUNCTION public.search_assets_hybrid_rrf(
  search_query    text,
  query_embedding extensions.vector(1536) DEFAULT NULL,
  page_limit      int  DEFAULT 10,
  offset_val      int  DEFAULT 0
)
RETURNS TABLE (
  id            uuid,
  ticker        character varying,
  platform      platform_type,
  external_name character varying,
  asset_type    asset_class_type,
  currency      currency_type,
  rrf_score     double precision
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, extensions
AS $$
  WITH
  -- ------------------------------------------------------------------
  -- Leg 1a: BM25 full-text search
  --   websearch_to_tsquery is robust: handles partial words, phrases,
  --   boolean operators and never throws on malformed input.
  --   'simple' dictionary preserves financial tickers as-is (no stemming).
  -- ------------------------------------------------------------------
  bm25 AS (
    SELECT
      id,
      ROW_NUMBER() OVER (
        ORDER BY ts_rank_cd(search_vector,
                            websearch_to_tsquery('simple', search_query),
                            32) DESC
      ) AS rank
    FROM public.assets
    WHERE search_vector @@ websearch_to_tsquery('simple', search_query)
    LIMIT 100
  ),

  -- ------------------------------------------------------------------
  -- Leg 1b: Trigram similarity fallback
  --   Fires only when BM25 returns 0 rows (e.g. the query is too short
  --   or contains special characters that don't produce tsquery tokens).
  --   Handles abbreviations, partial tickers and typos.
  -- ------------------------------------------------------------------
  trgm AS (
    SELECT
      id,
      ROW_NUMBER() OVER (
        ORDER BY similarity(
          lower(ticker || ' ' || COALESCE(external_name, '')),
          lower(search_query)
        ) DESC
      ) AS rank
    FROM public.assets
    WHERE
      NOT EXISTS (SELECT 1 FROM bm25)
      AND similarity(
            lower(ticker || ' ' || COALESCE(external_name, '')),
            lower(search_query)
          ) > 0.05
    LIMIT 100
  ),

  -- Merge: BM25 preferred; trigram takes over when BM25 is empty
  text_ranked AS (
    SELECT id, rank FROM bm25
    UNION ALL
    SELECT id, rank FROM trgm
  ),

  -- ------------------------------------------------------------------
  -- Leg 2: Vector (cosine distance via pgvector <=> operator)
  --   Only executes when the caller provides a pre-computed embedding.
  --   Skipped entirely when query_embedding IS NULL → BM25-only mode.
  -- ------------------------------------------------------------------
  vector_ranked AS (
    SELECT
      id,
      ROW_NUMBER() OVER (ORDER BY embedding <=> query_embedding) AS rank
    FROM public.assets
    WHERE query_embedding IS NOT NULL
      AND embedding IS NOT NULL
    LIMIT 100
  ),

  -- ------------------------------------------------------------------
  -- Reciprocal Rank Fusion   score = Σ 1 / (k + rank_i)   k = 60
  --   FULL OUTER JOIN so results found by only one leg still appear.
  -- ------------------------------------------------------------------
  rrf AS (
    SELECT
      COALESCE(t.id, v.id)                    AS id,
      COALESCE(1.0 / (60.0 + t.rank), 0.0)
        + COALESCE(1.0 / (60.0 + v.rank), 0.0) AS rrf_score
    FROM text_ranked  t
    FULL OUTER JOIN vector_ranked v ON t.id = v.id
  )

  SELECT
    a.id,
    a.ticker,
    a.platform,
    a.external_name,
    a.asset_type,
    a.currency,
    r.rrf_score
  FROM rrf r
  JOIN public.assets a ON a.id = r.id
  ORDER BY r.rrf_score DESC
  LIMIT  page_limit
  OFFSET offset_val;
$$;

COMMENT ON FUNCTION public.search_assets_hybrid_rrf IS
  'Hybrid search over the global asset catalog using Reciprocal Rank Fusion.
   Leg 1: BM25 full-text (search_vector) with trigram fallback.
   Leg 2: pgvector cosine similarity (optional — pass query_embedding to activate).
   Returns results ranked by combined RRF score (k=60).';

GRANT EXECUTE ON FUNCTION public.search_assets_hybrid_rrf(
  text, extensions.vector(1536), int, int
) TO anon, authenticated, service_role;
