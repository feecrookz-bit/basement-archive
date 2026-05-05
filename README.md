# Basement — Local Backend (Sprints 1–6)

Bare-metal local backend stack for the Basement project. PostgreSQL + PostGIS, MinIO (S3-compatible), and a Fastify + TypeScript backend exposing JWT auth, the WatermelonDB sync resolver, a server-rendered Bar Grid SVG heatmap, SmartTag geofence alarms, and Match Control + SSE event fan-out — all behind one `docker compose up`.

## Quick start

```sh
cp .env.example .env

docker compose up -d
docker compose ps                     # all healthy

# Apply migrations inside the backend container
docker compose exec backend npx prisma migrate deploy

# Bootstrap the first ADMIN (only works while no users exist)
curl -sX POST http://localhost:4000/auth/bootstrap-admin \
  -H 'content-type: application/json' \
  -d '{"email":"owner@example.com","password":"supersecret123","displayName":"Owner"}'
```

| Surface | URL | Notes |
|---|---|---|
| Backend API | <http://localhost:4000> | Fastify + structured JSON logs |
| MinIO console | <http://localhost:9001> | basement / basement_dev_secret |
| Postgres | `localhost:5432` | basement / basement_dev |

## Endpoints

| Method | Path | Auth | Min role | Purpose |
|---|---|---|---|---|
| GET  | `/healthz` | none | — | Liveness |
| GET  | `/readyz`  | none | — | Reports `server_rev` (DB-backed readiness) |
| POST | `/auth/bootstrap-admin` | none (one-shot) | — | First-run admin creation |
| POST | `/auth/login` | none | — | Email + password → JWT |
| GET  | `/auth/me` | JWT or service token | VIEWER | Caller introspection |
| POST | `/sync/pull` | JWT or service token | VIEWER | WatermelonDB pull (`{lastPulledRev}` → `{changes, timestamp}`) |
| POST | `/sync/push` | JWT or service token | VIEWER | WatermelonDB push, idempotent by id (UUIDv7) |
| GET  | `/bargrid/heatmap.svg` | JWT or service token | VIEWER | Server-rendered SVG heatmap (`?cell=20&pad=2`) |
| POST | `/smarttags/:id/ping` | JWT or service token | VIEWER | Heartbeat → geofence + low-battery alarm eval |
| POST | `/smarttags/alarms/:id/resolve` | JWT or service token | VIEWER | Mark alarm resolved |
| POST | `/safety/:id/transition` | JWT | OPERATOR | Server-authoritative state machine |
| POST | `/matchcontrol/rain-delay` | JWT | OPERATOR | Set RAIN_DELAY for N minutes |
| POST | `/matchcontrol/interval`  | JWT | OPERATOR | Set MATCH_INTERVAL for N minutes |
| POST | `/matchcontrol/clear`     | JWT | OPERATOR | Return gateway to ARMED |
| GET  | `/events` (SSE) | JWT or service token | VIEWER | Live stream of safety/alarm events |

**Auth modes**
- **JWT** — issued by `/auth/login`. Carries the user's role and powers role guards.
- **Service token** — `SYNC_TOKEN` from `.env`. For unattended sync clients (Flutter app). Acts at OPERATOR level but cannot reach ADMIN-only paths.

## Layout

```
docker-compose.yml             postgres + postgis, minio, mc bootstrap, backend
.env.example                   Copy to .env (gitignored)
backend/
  Dockerfile                   Node 20 + tsx watch
  package.json                 Fastify, Prisma, bcryptjs, jsonwebtoken, vitest, zod
  tsconfig.json                ESM NodeNext, strict + noUncheckedIndexedAccess
  vitest.config.ts             single-fork integration tests against the live DB
  src/
    server.ts                  app builder + listener
    env.ts                     zod-validated env
    prisma.ts                  Prisma client singleton
    auth.ts                    requireAuth, requireRole guards (hybrid JWT/service)
    audit.ts                   chain-aware audit log emitter
    jwt.ts password.ts         JWT sign/verify, bcrypt
    events.ts                  in-process event bus (Sprint 6 SSE feed)
    sync/                      tables registry, pull, push, geometry adapter
    routes/                    health, auth, sync, safety, heatmap, smarttags, matchcontrol
    seed/admin.ts              CLI: npm run seed:admin -- email password
  prisma/
    schema.prisma              Synced models + User + GeofenceAlarm
    migrations/
      0001_init                PostGIS, server_rev_seq, sync_touch, audit_chain
      0002_users_alarms        users, geofence_alarms, AuditAction additions
      0003_sync_touch_owns_created_at  Trigger owns createdAt on INSERT
  test/
    helpers.ts                 makeApp, resetDb, jwtAuth helper
    sync.test.ts auth.test.ts heatmap.test.ts geofence.test.ts matchcontrol.test.ts
infra/
  minio/README.md              Bucket bootstrap notes
  postgres/initdb/             drop *.sql here for first-run DB init
```

## Sync contract

Every synced model carries `id`, `createdAt`, `updatedAt`, `deletedAt`, and `serverRev`. The `sync_touch()` trigger sets all three timestamps and the global monotonic `serverRev` on every write — the pull cursor is a `serverRev` high-water mark, robust to clock skew.

Pull buckets:
- `created`  — rows where `createdAt == updatedAt` (never updated since insert)
- `updated`  — rows updated since the cursor
- `deleted`  — ids of soft-deleted rows (those with `deletedAt IS NOT NULL`)

`audit_logs` is append-only: an `audit_chain()` trigger sets `prevHash` / `rowHash` (sha256 chain), and INSTEAD-NOTHING rules block `UPDATE`/`DELETE`.

## Tests

```sh
docker compose exec -T -e NODE_ENV=test backend npm test
```

Vitest integration suite, 5 files / 34 tests, runs in a single fork against the live Postgres so triggers, geography, and the audit chain are all exercised. Each test truncates synced + audit + users tables; the `server_rev_seq` deliberately keeps incrementing.

## Local launch checklist

1. **Rotate secrets** — set `JWT_SECRET` (≥16 chars) and `SYNC_TOKEN` in `.env`. The defaults are flagged with `change-me`.
2. **Restart compose** — `docker compose up -d --force-recreate backend`.
3. **Apply migrations** — `docker compose exec backend npx prisma migrate deploy`.
4. **Bootstrap admin** — POST `/auth/bootstrap-admin` once, then save the credentials.
5. **Smoke** — login → pull → push → heatmap → match control round-trip.

What's *not* in this build (deliberate):
- Public TLS / domain — local only. Add Caddy in front when exposing beyond localhost.
- Flutter mobile app (Sprints 7–9 of original roadmap) — a multi-week build that doesn't fit a chat session. The HTTP contract is WatermelonDB-shaped so the client can be wired via stock `synchronize({ pullChanges, pushChanges })`.
- Real load test (Sprint 10 UAT) — the rate limit, monotonic cursor, and pooled Prisma client are sized for ≥50 concurrent users; a k6 script lives in your future.
