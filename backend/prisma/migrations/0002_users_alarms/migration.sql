-- Sprint 3 (users + JWT auth) and Sprint 5 (geofence alarms).

-- ============================================================
-- 1. Enums
-- ============================================================

CREATE TYPE "UserRole"    AS ENUM ('ADMIN','OPERATOR','VIEWER');
CREATE TYPE "AlarmReason" AS ENUM ('OUT_OF_GEOFENCE','STALE_HEARTBEAT','LOW_BATTERY');

-- Extend AuditAction with the new entries Sprint 3/5/6 emit.
ALTER TYPE "AuditAction" ADD VALUE IF NOT EXISTS 'GEOFENCE_ALARM';
ALTER TYPE "AuditAction" ADD VALUE IF NOT EXISTS 'TAG_PING';
ALTER TYPE "AuditAction" ADD VALUE IF NOT EXISTS 'USER_BOOTSTRAP';
ALTER TYPE "AuditAction" ADD VALUE IF NOT EXISTS 'LOGIN_FAIL';

-- ============================================================
-- 2. users (NOT synced to clients — never has serverRev/sync_touch)
-- ============================================================

CREATE TABLE "users" (
  "id"           TEXT PRIMARY KEY,
  "email"        TEXT NOT NULL,
  "passwordHash" TEXT NOT NULL,
  "displayName"  TEXT,
  "role"         "UserRole" NOT NULL DEFAULT 'VIEWER',
  "disabled"     BOOLEAN NOT NULL DEFAULT false,
  "createdAt"    TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "updatedAt"    TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "lastLogin"    TIMESTAMP(3)
);
CREATE UNIQUE INDEX "users_email_key" ON "users"("email");

-- ============================================================
-- 3. geofence_alarms (synced — clients see live alarms)
-- ============================================================

CREATE TABLE "geofence_alarms" (
  "id"         TEXT PRIMARY KEY,
  "tagId"      TEXT NOT NULL,
  "lat"        DOUBLE PRECISION NOT NULL,
  "lng"        DOUBLE PRECISION NOT NULL,
  "reason"     "AlarmReason" NOT NULL,
  "resolvedAt" TIMESTAMP(3),
  "createdAt"  TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "updatedAt"  TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "deletedAt"  TIMESTAMP(3),
  "serverRev"  BIGINT NOT NULL DEFAULT 0,
  CONSTRAINT "geofence_alarms_tagId_fkey"
    FOREIGN KEY ("tagId") REFERENCES "smart_tags"("id") ON DELETE CASCADE
);
CREATE INDEX "geofence_alarms_tagId_createdAt_idx" ON "geofence_alarms"("tagId","createdAt");
CREATE INDEX "geofence_alarms_resolvedAt_idx"      ON "geofence_alarms"("resolvedAt");
CREATE INDEX "geofence_alarms_updatedAt_id_idx"    ON "geofence_alarms"("updatedAt","id");
CREATE INDEX "geofence_alarms_serverRev_idx"       ON "geofence_alarms"("serverRev");

-- Reuse the sync_touch() function from migration 0001.
CREATE TRIGGER geofence_alarms_sync_touch
  BEFORE INSERT OR UPDATE ON "geofence_alarms"
  FOR EACH ROW EXECUTE FUNCTION sync_touch();
