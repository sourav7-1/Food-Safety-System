-- Apply this migration to a database created before the "Nearby Stalls"
-- map feature. Fresh installations already include this index through
-- database/schema.sql.
--
-- stalls.latitude/longitude (and their -90..90 / -180..180 CHECK
-- constraints) already exist from earlier work -- this migration only
-- adds the index. /customer/api/stalls/nearby filters on
-- "latitude IS NOT NULL AND longitude IS NOT NULL" before computing the
-- Haversine distance in the HAVING clause, so this composite index lets
-- MySQL skip stalls that have never had a location set instead of
-- scanning every row.
--
-- Note: a plain B-tree index like this cannot accelerate the radius
-- (HAVING distance_km <= :radius_km) filter itself -- that would need a
-- SPATIAL index over a POINT column, a larger schema change out of scope
-- here. At this project's scale (low hundreds of stalls), the full-table
-- Haversine scan the API route runs is fast enough without one; this
-- index only helps the NULL-location filter and keeps room to add a
-- spatial index later without another migration touching this column
-- pair.

USE smart_street_food_safety;

SET @stalls_lat_lng_index_exists = (
  SELECT COUNT(*)
  FROM information_schema.statistics
  WHERE table_schema = DATABASE()
    AND table_name = 'stalls'
    AND index_name = 'idx_stalls_lat_lng'
);

SET @stalls_lat_lng_index_sql = IF(
  @stalls_lat_lng_index_exists = 0,
  'CREATE INDEX idx_stalls_lat_lng ON stalls (latitude, longitude)',
  'SELECT ''idx_stalls_lat_lng already exists'' AS migration_status'
);

PREPARE stalls_lat_lng_index_statement FROM @stalls_lat_lng_index_sql;
EXECUTE stalls_lat_lng_index_statement;
DEALLOCATE PREPARE stalls_lat_lng_index_statement;
