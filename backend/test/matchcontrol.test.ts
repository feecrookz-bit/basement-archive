import { afterAll, beforeEach, describe, expect, it } from "vitest";
import { auth, jwtAuth, makeApp, resetDb } from "./helpers.js";
import { prisma } from "../src/prisma.js";
import { bus, type BasementEvent } from "../src/events.js";

const app = await makeApp();
afterAll(async () => { await app.close(); await prisma.$disconnect(); });

beforeEach(async () => {
  await resetDb();
  await app.inject({
    method: "POST", url: "/sync/push", headers: auth,
    payload: { changes: { safety_gateways: { created: [
      { id: "arena", name: "arena", state: "ARMED" },
    ] } } },
  });
});

describe("/matchcontrol/*", () => {
  it("rain-delay sets state and rainDelayUntil ~now+15min", async () => {
    const r = await app.inject({
      method: "POST", url: "/matchcontrol/rain-delay",
      headers: jwtAuth("OPERATOR"),
      payload: { gatewayId: "arena", durationMinutes: 15, reason: "thunder" },
    });
    expect(r.statusCode).toBe(200);
    const body = r.json();
    expect(body).toMatchObject({ gatewayId: "arena", fromState: "ARMED", toState: "RAIN_DELAY" });
    const gw = await prisma.safetyGateway.findUnique({ where: { id: "arena" } });
    expect(gw?.state).toBe("RAIN_DELAY");
    expect(gw?.rainDelayUntil).not.toBeNull();
    const transitions = await prisma.safetyTransition.count({ where: { gatewayId: "arena" } });
    expect(transitions).toBe(1);
  });

  it("interval sets MATCH_INTERVAL", async () => {
    const r = await app.inject({
      method: "POST", url: "/matchcontrol/interval",
      headers: jwtAuth("OPERATOR"),
      payload: { gatewayId: "arena", durationMinutes: 5 },
    });
    expect(r.statusCode).toBe(200);
    expect(r.json().toState).toBe("MATCH_INTERVAL");
  });

  it("clear returns to ARMED", async () => {
    await app.inject({
      method: "POST", url: "/matchcontrol/rain-delay",
      headers: jwtAuth("OPERATOR"),
      payload: { gatewayId: "arena", durationMinutes: 15 },
    });
    const r = await app.inject({
      method: "POST", url: "/matchcontrol/clear",
      headers: jwtAuth("OPERATOR"),
      payload: { gatewayId: "arena", reason: "skies cleared" },
    });
    expect(r.statusCode).toBe(200);
    const body = r.json();
    expect(body.toState).toBe("ARMED");
  });

  it("VIEWER gets 403", async () => {
    const r = await app.inject({
      method: "POST", url: "/matchcontrol/rain-delay",
      headers: jwtAuth("VIEWER"),
      payload: { gatewayId: "arena", durationMinutes: 1 },
    });
    expect(r.statusCode).toBe(403);
  });

  it("emits an event on the in-process bus", async () => {
    const events: BasementEvent[] = [];
    const off = bus.onEvent((ev) => events.push(ev));

    await app.inject({
      method: "POST", url: "/matchcontrol/rain-delay",
      headers: jwtAuth("OPERATOR"),
      payload: { gatewayId: "arena", durationMinutes: 1 },
    });

    off();
    expect(events.some(e => e.type === "rain_delay.set")).toBe(true);
  });

  it("404 for unknown gateway", async () => {
    const r = await app.inject({
      method: "POST", url: "/matchcontrol/rain-delay",
      headers: jwtAuth("OPERATOR"),
      payload: { gatewayId: "missing", durationMinutes: 1 },
    });
    expect(r.statusCode).toBe(404);
  });
});
