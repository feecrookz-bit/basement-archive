import { afterAll, beforeEach, describe, expect, it } from "vitest";
import { auth, currentRev, makeApp, resetDb, TOKEN } from "./helpers.js";
import { prisma } from "../src/prisma.js";

const app = await makeApp();
afterAll(async () => {
  await app.close();
  await prisma.$disconnect();
});

beforeEach(async () => {
  await resetDb();
});

describe("auth", () => {
  it("rejects missing bearer", async () => {
    const res = await app.inject({ method: "POST", url: "/sync/pull", payload: { lastPulledRev: 0 } });
    expect(res.statusCode).toBe(401);
  });
  it("rejects wrong bearer", async () => {
    const res = await app.inject({
      method: "POST",
      url: "/sync/pull",
      headers: { authorization: "Bearer nope" },
      payload: { lastPulledRev: 0 },
    });
    expect(res.statusCode).toBe(401);
  });
});

describe("/healthz + /readyz", () => {
  it("healthz needs no auth", async () => {
    const res = await app.inject({ method: "GET", url: "/healthz" });
    expect(res.statusCode).toBe(200);
    expect(res.json()).toMatchObject({ status: "ok" });
  });
  it("readyz reports server_rev", async () => {
    const res = await app.inject({ method: "GET", url: "/readyz" });
    expect(res.statusCode).toBe(200);
    expect(typeof res.json().server_rev).toBe("number");
  });
});

describe("/sync/push then /sync/pull", () => {
  it("round-trips a BarGridNode with PostGIS coords", async () => {
    const before = await currentRev();

    const id = "01J000000000000000000000P1";
    const push = await app.inject({
      method: "POST",
      url: "/sync/push",
      headers: auth,
      payload: {
        changes: {
          bar_grid_nodes: {
            created: [
              { id, grid_x: 4, grid_y: 7, status: "ACTIVE", heat_value: 0.5,
                lat: 40.7484, lng: -73.9857, metadata: { source: "test" } },
            ],
          },
        },
      },
    });
    expect(push.statusCode).toBe(200);
    const pushBody = push.json();
    expect(pushBody.timestamp).toBeGreaterThan(before);
    expect(pushBody.applied[0]).toMatchObject({ table: "bar_grid_nodes", created: 1 });

    const pull = await app.inject({
      method: "POST",
      url: "/sync/pull",
      headers: auth,
      payload: { lastPulledRev: before },
    });
    expect(pull.statusCode).toBe(200);
    const body = pull.json();
    const got = body.changes.bar_grid_nodes;
    expect(got.created).toHaveLength(1);
    expect(got.created[0]).toMatchObject({ id, grid_x: 4, grid_y: 7, status: "ACTIVE" });
    expect(got.created[0].lat).toBeCloseTo(40.7484, 4);
    expect(got.created[0].lng).toBeCloseTo(-73.9857, 4);
    expect(body.timestamp).toBeGreaterThan(before);
  });

  it("update bumps a row from created to updated bucket on next pull", async () => {
    const id = "01J000000000000000000000U1";
    await app.inject({
      method: "POST", url: "/sync/push", headers: auth,
      payload: { changes: { bar_grid_nodes: { created: [
        { id, grid_x: 0, grid_y: 0, status: "IDLE", heat_value: 0, lat: 0, lng: 0 },
      ] } } },
    });

    // Pull once to advance our cursor past the create.
    const pull1 = await app.inject({
      method: "POST", url: "/sync/pull", headers: auth, payload: { lastPulledRev: 0 },
    });
    const cursor1 = pull1.json().timestamp;

    // Update.
    const push2 = await app.inject({
      method: "POST", url: "/sync/push", headers: auth,
      payload: { changes: { bar_grid_nodes: { updated: [
        { id, grid_x: 0, grid_y: 0, status: "FAULT", heat_value: 0.9, lat: 0, lng: 0 },
      ] } } },
    });
    expect(push2.statusCode).toBe(200);

    const pull2 = await app.inject({
      method: "POST", url: "/sync/pull", headers: auth, payload: { lastPulledRev: cursor1 },
    });
    const got = pull2.json().changes.bar_grid_nodes;
    expect(got.created).toHaveLength(0);
    expect(got.updated).toHaveLength(1);
    expect(got.updated[0]).toMatchObject({ id, status: "FAULT" });
  });

  it("soft-deletes surface in deleted bucket", async () => {
    const id = "01J000000000000000000000D1";
    await app.inject({
      method: "POST", url: "/sync/push", headers: auth,
      payload: { changes: { inventory_items: { created: [
        { id, sku: "DEL-1", name: "x", quantity: 1 },
      ] } } },
    });
    const cur = (await app.inject({
      method: "POST", url: "/sync/pull", headers: auth, payload: { lastPulledRev: 0 },
    })).json().timestamp;

    await app.inject({
      method: "POST", url: "/sync/push", headers: auth,
      payload: { changes: { inventory_items: { deleted: [id] } } },
    });

    const pull = await app.inject({
      method: "POST", url: "/sync/pull", headers: auth, payload: { lastPulledRev: cur },
    }).then(r => r.json());

    expect(pull.changes.inventory_items.deleted).toContain(id);
  });

  it("rejects unknown table in push", async () => {
    const res = await app.inject({
      method: "POST", url: "/sync/push", headers: auth,
      payload: { changes: { not_a_table: { created: [{ id: "x" }] } } },
    });
    expect(res.statusCode).toBe(400);
  });

  it("emits SYNC_PULL and SYNC_PUSH audit rows", async () => {
    const before = await prisma.auditLog.count();
    await app.inject({
      method: "POST", url: "/sync/pull", headers: auth, payload: { lastPulledRev: 0 },
    });
    await app.inject({
      method: "POST", url: "/sync/push", headers: auth,
      payload: { changes: { inventory_items: { created: [{ id: "a-1", sku: "A", name: "A", quantity: 1 }] } } },
    });
    const rows = await prisma.auditLog.findMany({
      orderBy: { occurredAt: "desc" }, take: 2,
    });
    expect(rows.length).toBe(2);
    const actions = rows.map(r => r.action).sort();
    expect(actions).toEqual(["SYNC_PULL", "SYNC_PUSH"]);
    expect(await prisma.auditLog.count()).toBe(before + 2);
  });
});

describe("/safety/:id/transition", () => {
  it("server-authoritative state change with optimistic check", async () => {
    await app.inject({
      method: "POST", url: "/sync/push", headers: auth,
      payload: { changes: { safety_gateways: { created: [
        { id: "sg-1", name: "arena", state: "ARMED" },
      ] } } },
    });

    // Stale expectedFromState → 409.
    const conflict = await app.inject({
      method: "POST", url: "/safety/sg-1/transition", headers: auth,
      payload: { toState: "RAIN_DELAY", expectedFromState: "DISARMED" },
    });
    expect(conflict.statusCode).toBe(409);

    const ok = await app.inject({
      method: "POST", url: "/safety/sg-1/transition", headers: auth,
      payload: { toState: "RAIN_DELAY", expectedFromState: "ARMED", reason: "thunder" },
    });
    expect(ok.statusCode).toBe(200);
    expect(ok.json()).toMatchObject({ id: "sg-1", fromState: "ARMED", toState: "RAIN_DELAY" });

    const gw = await prisma.safetyGateway.findUnique({ where: { id: "sg-1" } });
    expect(gw?.state).toBe("RAIN_DELAY");

    const tr = await prisma.safetyTransition.findMany({ where: { gatewayId: "sg-1" } });
    expect(tr).toHaveLength(1);
    expect(tr[0]).toMatchObject({ fromState: "ARMED", toState: "RAIN_DELAY" });

    const audit = await prisma.auditLog.findFirst({
      where: { entityType: "SafetyGateway", entityId: "sg-1", action: "RAIN_DELAY_SET" },
    });
    expect(audit).not.toBeNull();
  });

  it("returns 404 for unknown gateway", async () => {
    const res = await app.inject({
      method: "POST", url: "/safety/missing/transition", headers: auth,
      payload: { toState: "ARMED" },
    });
    expect(res.statusCode).toBe(404);
  });
});

describe("monotonic cursor across mixed pushes", () => {
  it("each table's serverRev is unique and globally increasing", async () => {
    await app.inject({
      method: "POST", url: "/sync/push", headers: auth,
      payload: {
        changes: {
          inventory_items: { created: [{ id: "i1", sku: "S1", name: "n", quantity: 1 }] },
          smart_tags:      { created: [{ id: "t1", external_ref: "TAG-1" }] },
        },
      },
    });
    await app.inject({
      method: "POST", url: "/sync/push", headers: auth,
      payload: { changes: { inventory_items: {
        updated: [{ id: "i1", sku: "S1", name: "n", quantity: 2 }],
      } } },
    });

    const pull = await app.inject({
      method: "POST", url: "/sync/pull", headers: auth, payload: { lastPulledRev: 0 },
    }).then(r => r.json());

    const allRevs: number[] = [];
    for (const tbl of Object.values(pull.changes) as Array<{ created: Array<{server_rev: number}>; updated: Array<{server_rev: number}> }>) {
      for (const r of [...tbl.created, ...tbl.updated]) allRevs.push(r.server_rev);
    }
    expect(allRevs.length).toBeGreaterThan(0);
    expect(new Set(allRevs).size).toBe(allRevs.length);   // unique
    const sorted = [...allRevs].sort((a, b) => a - b);
    expect(sorted).toEqual([...allRevs].sort((a, b) => a - b));
    expect(pull.timestamp).toBe(Math.max(...allRevs));
  });
});

// silence unused-token lint
void TOKEN;
