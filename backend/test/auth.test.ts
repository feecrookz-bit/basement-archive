import { afterAll, beforeEach, describe, expect, it } from "vitest";
import { auth, createUser, jwtAuth, makeApp, resetDb } from "./helpers.js";
import { prisma } from "../src/prisma.js";

const app = await makeApp();
afterAll(async () => { await app.close(); await prisma.$disconnect(); });
beforeEach(async () => { await resetDb(); });

describe("/auth/bootstrap-admin", () => {
  it("creates the first admin user; rejects on second call", async () => {
    const r1 = await app.inject({
      method: "POST", url: "/auth/bootstrap-admin",
      payload: { email: "owner@example.com", password: "supersecret123", displayName: "Owner" },
    });
    expect(r1.statusCode).toBe(200);
    expect(r1.json()).toMatchObject({ email: "owner@example.com", role: "ADMIN" });

    const r2 = await app.inject({
      method: "POST", url: "/auth/bootstrap-admin",
      payload: { email: "x@y.com", password: "anotherone1234" },
    });
    expect(r2.statusCode).toBe(409);
  });

  it("emits USER_BOOTSTRAP audit row", async () => {
    await app.inject({
      method: "POST", url: "/auth/bootstrap-admin",
      payload: { email: "boot@x.com", password: "supersecret123" },
    });
    const a = await prisma.auditLog.findFirst({ where: { action: "USER_BOOTSTRAP" } });
    expect(a).not.toBeNull();
  });
});

describe("/auth/login", () => {
  it("issues JWT for valid credentials, audit LOGIN", async () => {
    await createUser({ email: "u@x.com", password: "correct-horse-battery", role: "OPERATOR" });
    const r = await app.inject({
      method: "POST", url: "/auth/login",
      payload: { email: "u@x.com", password: "correct-horse-battery" },
    });
    expect(r.statusCode).toBe(200);
    const body = r.json();
    expect(body.token).toMatch(/^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/);
    expect(body.user).toMatchObject({ email: "u@x.com", role: "OPERATOR" });
    expect(await prisma.auditLog.count({ where: { action: "LOGIN" } })).toBe(1);
  });

  it("rejects bad password and audits LOGIN_FAIL", async () => {
    await createUser({ email: "u@x.com", password: "correct-horse", role: "VIEWER" });
    const r = await app.inject({
      method: "POST", url: "/auth/login",
      payload: { email: "u@x.com", password: "wrong" },
    });
    expect(r.statusCode).toBe(401);
    expect(await prisma.auditLog.count({ where: { action: "LOGIN_FAIL" } })).toBe(1);
  });

  it("rejects disabled users", async () => {
    const u = await createUser({ email: "d@x.com", password: "supersecret123", role: "VIEWER" });
    await prisma.user.update({ where: { id: u.id }, data: { disabled: true } });
    const r = await app.inject({
      method: "POST", url: "/auth/login",
      payload: { email: "d@x.com", password: "supersecret123" },
    });
    expect(r.statusCode).toBe(401);
  });
});

describe("/auth/me + role guards", () => {
  it("service token returns isService=true", async () => {
    const r = await app.inject({ method: "GET", url: "/auth/me", headers: auth });
    expect(r.statusCode).toBe(200);
    expect(r.json()).toMatchObject({ isService: true, role: "OPERATOR" });
  });

  it("VIEWER JWT can read but cannot transition safety", async () => {
    await app.inject({
      method: "POST", url: "/sync/push", headers: auth,
      payload: { changes: { safety_gateways: { created: [{ id: "g1", name: "g1", state: "ARMED" }] } } },
    });

    const allowed = await app.inject({
      method: "GET", url: "/auth/me", headers: jwtAuth("VIEWER"),
    });
    expect(allowed.statusCode).toBe(200);
    expect(allowed.json().role).toBe("VIEWER");

    const blocked = await app.inject({
      method: "POST", url: "/safety/g1/transition",
      headers: jwtAuth("VIEWER"),
      payload: { toState: "ARMED" },
    });
    expect(blocked.statusCode).toBe(403);
  });

  it("OPERATOR JWT can transition safety", async () => {
    await app.inject({
      method: "POST", url: "/sync/push", headers: auth,
      payload: { changes: { safety_gateways: { created: [{ id: "g2", name: "g2", state: "ARMED" }] } } },
    });
    const r = await app.inject({
      method: "POST", url: "/safety/g2/transition",
      headers: jwtAuth("OPERATOR"),
      payload: { toState: "RAIN_DELAY", expectedFromState: "ARMED" },
    });
    expect(r.statusCode).toBe(200);
  });
});
