-- Basement Sprint 1 — initial migration.
--
-- This file is hand-authored. It contains:
--   1. Table DDL Prisma generates from schema.prisma.
--   2. PostGIS / pgcrypto extensions and the geography column ALTER.
--   3. The serverRev sequence + sync_touch() trigger applied to every synced table.
--   4. The audit_chain() trigger and append-only rules on audit_logs.
--
-- Run via:  npx prisma migrate dev   (in the backend container)
-- After editing schema.prisma in future sprints, generate a new migration with
-- `prisma migrate dev --create-only` and merge any required raw SQL into it.

-- ============================================================
-- 1. Extensions
-- ============================================================

CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ============================================================
-- 2. Enums
-- ============================================================

CREATE TYPE "BarGridStatus" AS ENUM ('IDLE','ACTIVE','FAULT','OFFLINE','RAIN_DELAYED');
CREATE TYPE "AuditAction"   AS ENUM ('CREATE','UPDATE','DELETE','LOGIN','LOGOUT','SAFETY_OVERRIDE','RAIN_DELAY_SET','RAIN_DELAY_CLEAR','MATCH_INTERVAL_SET','SYNC_PUSH','SYNC_PULL');
CREATE TYPE "SafetyState"   AS ENUM ('ARMED','DISARMED','ESTOP','RAIN_DELAY','MATCH_INTERVAL');

-- ============================================================
-- 3. Tables
-- ============================================================

-- BarGrid nodes
CREATE TABLE "bar_grid_nodes" (
  "id"        TEXT PRIMARY KEY,
  "gridX"     INTEGER NOT NULL,
  "gridY"     INTEGER NOT NULL,
  -- Initially TEXT so Prisma's Unsupported type maps cleanly; altered to geography below.
  "location"  TEXT,
  "status"    "BarGridStatus" NOT NULL DEFAULT 'IDLE',
  "heatValue" DOUBLE PRECISION NOT NULL DEFAULT 0,
  "metadata"  JSONB NOT NULL DEFAULT '{}',
  "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "updatedAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "deletedAt" TIMESTAMP(3),
  "serverRev" BIGINT NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX "bar_grid_nodes_gridX_gridY_key"  ON "bar_grid_nodes"("gridX","gridY");
CREATE INDEX        "bar_grid_nodes_updatedAt_id_idx" ON "bar_grid_nodes"("updatedAt","id");
CREATE INDEX        "bar_grid_nodes_serverRev_idx"   ON "bar_grid_nodes"("serverRev");
CREATE INDEX        "bar_grid_nodes_deletedAt_idx"   ON "bar_grid_nodes"("deletedAt");

-- Convert location to PostGIS geography + spatial index.
ALTER TABLE "bar_grid_nodes"
  ALTER COLUMN "location" TYPE geography(Point, 4326)
  USING NULLIF("location", '')::geography;
CREATE INDEX "bar_grid_nodes_location_gix" ON "bar_grid_nodes" USING GIST ("location");

-- SmartTags
CREATE TABLE "smart_tags" (
  "id"          TEXT PRIMARY KEY,
  "nodeId"      TEXT,
  "externalRef" TEXT NOT NULL,
  "geofenceWkt" TEXT,
  "lastSeenAt"  TIMESTAMP(3),
  "battery"     INTEGER,
  "createdAt"   TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "updatedAt"   TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "deletedAt"   TIMESTAMP(3),
  "serverRev"   BIGINT NOT NULL DEFAULT 0,
  CONSTRAINT "smart_tags_nodeId_fkey"
    FOREIGN KEY ("nodeId") REFERENCES "bar_grid_nodes"("id") ON DELETE SET NULL
);
CREATE UNIQUE INDEX "smart_tags_externalRef_key"   ON "smart_tags"("externalRef");
CREATE INDEX        "smart_tags_updatedAt_id_idx"  ON "smart_tags"("updatedAt","id");
CREATE INDEX        "smart_tags_serverRev_idx"    ON "smart_tags"("serverRev");

-- InventoryItems
CREATE TABLE "inventory_items" (
  "id"          TEXT PRIMARY KEY,
  "sku"         TEXT NOT NULL,
  "name"        TEXT NOT NULL,
  "quantity"    INTEGER NOT NULL DEFAULT 0,
  "unit"        TEXT NOT NULL DEFAULT 'ea',
  "binLocation" TEXT,
  "mediaKey"    TEXT,
  "attributes"  JSONB NOT NULL DEFAULT '{}',
  "createdAt"   TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "updatedAt"   TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "deletedAt"   TIMESTAMP(3),
  "serverRev"   BIGINT NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX "inventory_items_sku_key"          ON "inventory_items"("sku");
CREATE INDEX        "inventory_items_updatedAt_id_idx" ON "inventory_items"("updatedAt","id");
CREATE INDEX        "inventory_items_serverRev_idx"   ON "inventory_items"("serverRev");

-- InventoryMovements
CREATE TABLE "inventory_movements" (
  "id"         TEXT PRIMARY KEY,
  "itemId"     TEXT NOT NULL,
  "delta"      INTEGER NOT NULL,
  "reason"     TEXT NOT NULL,
  "actorId"    TEXT,
  "occurredAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "createdAt"  TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "updatedAt"  TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "deletedAt"  TIMESTAMP(3),
  "serverRev"  BIGINT NOT NULL DEFAULT 0,
  CONSTRAINT "inventory_movements_itemId_fkey"
    FOREIGN KEY ("itemId") REFERENCES "inventory_items"("id") ON DELETE RESTRICT
);
CREATE INDEX "inventory_movements_itemId_occurredAt_idx" ON "inventory_movements"("itemId","occurredAt");
CREATE INDEX "inventory_movements_updatedAt_id_idx"      ON "inventory_movements"("updatedAt","id");
CREATE INDEX "inventory_movements_serverRev_idx"        ON "inventory_movements"("serverRev");

-- AuditLogs (append-only)
CREATE TABLE "audit_logs" (
  "id"         TEXT PRIMARY KEY,
  "occurredAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "actorId"    TEXT,
  "actorRole"  TEXT,
  "action"     "AuditAction" NOT NULL,
  "entityType" TEXT NOT NULL,
  "entityId"   TEXT,
  "before"     JSONB,
  "after"      JSONB,
  "ip"         TEXT,
  "userAgent"  TEXT,
  "prevHash"   TEXT,
  "rowHash"    TEXT NOT NULL DEFAULT ''
);
CREATE INDEX "audit_logs_occurredAt_idx"            ON "audit_logs"("occurredAt");
CREATE INDEX "audit_logs_entityType_entityId_idx"  ON "audit_logs"("entityType","entityId");
CREATE INDEX "audit_logs_actorId_occurredAt_idx"   ON "audit_logs"("actorId","occurredAt");

-- SafetyGateways
CREATE TABLE "safety_gateways" (
  "id"             TEXT PRIMARY KEY,
  "name"           TEXT NOT NULL,
  "state"          "SafetyState" NOT NULL DEFAULT 'DISARMED',
  "rainDelayUntil" TIMESTAMP(3),
  "intervalUntil"  TIMESTAMP(3),
  "lastHeartbeat"  TIMESTAMP(3),
  "reason"         TEXT,
  "setByActorId"   TEXT,
  "createdAt"      TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "updatedAt"      TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "deletedAt"      TIMESTAMP(3),
  "serverRev"      BIGINT NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX "safety_gateways_name_key"          ON "safety_gateways"("name");
CREATE INDEX        "safety_gateways_updatedAt_id_idx" ON "safety_gateways"("updatedAt","id");
CREATE INDEX        "safety_gateways_serverRev_idx"   ON "safety_gateways"("serverRev");

-- SafetyTransitions
CREATE TABLE "safety_transitions" (
  "id"         TEXT PRIMARY KEY,
  "gatewayId"  TEXT NOT NULL,
  "fromState"  "SafetyState" NOT NULL,
  "toState"    "SafetyState" NOT NULL,
  "actorId"    TEXT,
  "reason"     TEXT,
  "occurredAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "createdAt"  TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "updatedAt"  TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "deletedAt"  TIMESTAMP(3),
  "serverRev"  BIGINT NOT NULL DEFAULT 0,
  CONSTRAINT "safety_transitions_gatewayId_fkey"
    FOREIGN KEY ("gatewayId") REFERENCES "safety_gateways"("id") ON DELETE CASCADE
);
CREATE INDEX "safety_transitions_gatewayId_occurredAt_idx" ON "safety_transitions"("gatewayId","occurredAt");
CREATE INDEX "safety_transitions_updatedAt_id_idx"         ON "safety_transitions"("updatedAt","id");
CREATE INDEX "safety_transitions_serverRev_idx"           ON "safety_transitions"("serverRev");

-- ============================================================
-- 4. Sync primitives: monotonic serverRev + updated_at trigger
-- ============================================================

CREATE SEQUENCE IF NOT EXISTS server_rev_seq;

CREATE OR REPLACE FUNCTION sync_touch() RETURNS trigger AS $$
BEGIN
  NEW."updatedAt" := now();
  NEW."serverRev" := nextval('server_rev_seq');
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY[
    'bar_grid_nodes','smart_tags',
    'inventory_items','inventory_movements',
    'safety_gateways','safety_transitions'
  ] LOOP
    EXECUTE format(
      'CREATE TRIGGER %I_sync_touch BEFORE INSERT OR UPDATE ON %I
         FOR EACH ROW EXECUTE FUNCTION sync_touch();',
      t, t
    );
  END LOOP;
END$$;

-- ============================================================
-- 5. Audit log hash chain + append-only enforcement
-- ============================================================

CREATE OR REPLACE FUNCTION audit_chain() RETURNS trigger AS $$
DECLARE last_hash TEXT;
BEGIN
  SELECT "rowHash" INTO last_hash
    FROM audit_logs
    ORDER BY "occurredAt" DESC, "id" DESC
    LIMIT 1;

  NEW."prevHash" := last_hash;
  NEW."rowHash"  := encode(
    digest(
      coalesce(last_hash, '') ||
      NEW."id" ||
      NEW."action"::text ||
      coalesce(NEW."entityType",'') ||
      coalesce(NEW."entityId",'') ||
      coalesce(NEW."before"::text,'') ||
      coalesce(NEW."after"::text,'') ||
      NEW."occurredAt"::text,
      'sha256'
    ),
    'hex'
  );
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER audit_logs_chain
  BEFORE INSERT ON "audit_logs"
  FOR EACH ROW EXECUTE FUNCTION audit_chain();

-- Append-only: silently drop UPDATE/DELETE attempts.
CREATE RULE audit_logs_no_update AS ON UPDATE TO "audit_logs" DO INSTEAD NOTHING;
CREATE RULE audit_logs_no_delete AS ON DELETE TO "audit_logs" DO INSTEAD NOTHING;
