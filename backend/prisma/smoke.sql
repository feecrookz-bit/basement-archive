-- Sprint 1 smoke test — proves PostGIS, sync_touch, audit_chain, and append-only rules.

\echo === 1. Insert two BarGridNodes (PostGIS Point) ===
INSERT INTO bar_grid_nodes (id, "gridX", "gridY", location, status, "heatValue")
VALUES
  ('01J000000000000000000000A1', 0, 0,
   ST_SetSRID(ST_MakePoint(-73.9857, 40.7484), 4326)::geography, 'ACTIVE', 0.42),
  ('01J000000000000000000000B2', 1, 0,
   ST_SetSRID(ST_MakePoint(-73.9851, 40.7480), 4326)::geography, 'IDLE', 0.10);

SELECT id, "gridX", "gridY", status, "heatValue",
       ST_AsText(location::geometry) AS coords,
       "serverRev"
  FROM bar_grid_nodes
  ORDER BY "serverRev";

\echo === 2. Update first node — serverRev must increment, updatedAt must advance ===
SELECT pg_sleep(0.05);
UPDATE bar_grid_nodes
   SET status = 'FAULT', "heatValue" = 0.91
 WHERE id = '01J000000000000000000000A1';

SELECT id, status, "heatValue", "serverRev",
       "updatedAt" > "createdAt" AS bumped_updated_at
  FROM bar_grid_nodes
  ORDER BY "serverRev";

\echo === 3. Spatial query — find nodes within 100m of Times Square ===
SELECT id, ST_Distance(
         location,
         ST_SetSRID(ST_MakePoint(-73.9855, 40.7484), 4326)::geography
       )::int AS meters
  FROM bar_grid_nodes
  WHERE ST_DWithin(location,
                   ST_SetSRID(ST_MakePoint(-73.9855, 40.7484), 4326)::geography,
                   100);

\echo === 4. Pull-cursor simulation: rows with serverRev > 0 ===
SELECT id, "serverRev", "deletedAt" IS NOT NULL AS is_deleted
  FROM bar_grid_nodes
  WHERE "serverRev" > 0
  ORDER BY "serverRev";

\echo === 5. Soft-delete second node — surfaces as a "deleted" change to sync ===
UPDATE bar_grid_nodes
   SET "deletedAt" = now()
 WHERE id = '01J000000000000000000000B2';

SELECT id, "serverRev", "deletedAt" IS NOT NULL AS is_deleted
  FROM bar_grid_nodes
  ORDER BY "serverRev";

\echo === 6. Audit log hash chain ===
INSERT INTO audit_logs (id, action, "entityType", "entityId", "actorId", before, after)
VALUES
  ('a1', 'CREATE', 'BarGridNode', '01J000000000000000000000A1', 'user-alice', NULL,
   '{"status":"ACTIVE"}'::jsonb),
  ('a2', 'UPDATE', 'BarGridNode', '01J000000000000000000000A1', 'user-alice',
   '{"status":"ACTIVE"}'::jsonb, '{"status":"FAULT"}'::jsonb);

SELECT id, action, "entityId",
       substring("prevHash" from 1 for 12) AS prev_hash_12,
       substring("rowHash"  from 1 for 12) AS row_hash_12
  FROM audit_logs
  ORDER BY "occurredAt", id;

\echo === 7. Verify chain link: a2.prevHash == a1.rowHash ===
SELECT (SELECT "prevHash" FROM audit_logs WHERE id='a2')
       = (SELECT "rowHash"  FROM audit_logs WHERE id='a1') AS chain_intact;

\echo === 8. Append-only enforcement: UPDATE is silently dropped ===
UPDATE audit_logs SET "actorId" = 'tampered' WHERE id = 'a1';
SELECT id, "actorId" FROM audit_logs WHERE id='a1';   -- still 'user-alice'

DELETE FROM audit_logs WHERE id = 'a1';
SELECT count(*) AS audit_row_count FROM audit_logs;   -- still 2

\echo === 9. SafetyGateway initial state + transition ===
INSERT INTO safety_gateways (id, name, state, reason, "setByActorId")
VALUES ('sg-main', 'main-arena', 'ARMED', 'sprint-1 smoke', 'user-alice');

INSERT INTO safety_transitions (id, "gatewayId", "fromState", "toState", "actorId", reason)
VALUES ('st-1', 'sg-main', 'ARMED', 'RAIN_DELAY', 'user-alice', 'thunder cell ETA 5min');

UPDATE safety_gateways
   SET state = 'RAIN_DELAY', "rainDelayUntil" = now() + interval '15 minutes'
 WHERE id = 'sg-main';

SELECT id, state, "rainDelayUntil", "serverRev" FROM safety_gateways;
SELECT id, "fromState", "toState", reason, "serverRev" FROM safety_transitions;

\echo === 10. Inventory + movement ===
INSERT INTO inventory_items (id, sku, name, quantity, unit, "binLocation")
VALUES ('inv-1', 'BAR-001', 'Heat Bar', 100, 'ea', 'A-12');

INSERT INTO inventory_movements (id, "itemId", delta, reason, "actorId")
VALUES ('mv-1', 'inv-1', -3, 'CONSUME', 'user-alice');

UPDATE inventory_items SET quantity = quantity - 3 WHERE id = 'inv-1';

SELECT id, sku, quantity, "serverRev" FROM inventory_items;

\echo === 11. Final pull high-water mark ===
SELECT 'bar_grid_nodes'      AS tbl, max("serverRev") FROM bar_grid_nodes
UNION ALL SELECT 'safety_gateways',     max("serverRev") FROM safety_gateways
UNION ALL SELECT 'safety_transitions',  max("serverRev") FROM safety_transitions
UNION ALL SELECT 'inventory_items',     max("serverRev") FROM inventory_items
UNION ALL SELECT 'inventory_movements', max("serverRev") FROM inventory_movements
UNION ALL SELECT 'smart_tags',          max("serverRev") FROM smart_tags
ORDER BY tbl;

\echo === 12. Clean up so the smoke is rerunnable ===
DELETE FROM inventory_movements WHERE id='mv-1';
DELETE FROM inventory_items     WHERE id='inv-1';
DELETE FROM safety_transitions  WHERE id='st-1';
DELETE FROM safety_gateways     WHERE id='sg-main';
DELETE FROM bar_grid_nodes
  WHERE id IN ('01J000000000000000000000A1','01J000000000000000000000B2');
-- audit_logs cannot be deleted (append-only) — that's the point. Leave them.
