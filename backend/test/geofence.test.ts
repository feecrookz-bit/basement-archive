import { afterAll, beforeEach, describe, expect, it } from "vitest";
import { auth, makeApp, resetDb } from "./helpers.js";
import { prisma } from "../src/prisma.js";

const app = await makeApp();
afterAll(async () => { await app.close(); await prisma.$disconnect(); });
beforeEach(async () => { await resetDb(); });

// 1km square fence centered roughly on (40.7484, -73.9857).
const FENCE_WKT =
  "POLYGON((-73.99 40.74, -73.97 40.74, -73.97 40.76, -73.99 40.76, -73.99 40.74))";

async function createTag(id: string, geofence: string | null) {
  await app.inject({
    method: "POST", url: "/sync/push", headers: auth,
    payload: { changes: { smart_tags: { created: [{
      id, external_ref: `EXT-${id}`, geofence_wkt: geofence, battery: 90,
    }] } } },
  });
}

describe("/smarttags/:id/ping", () => {
  it("inside fence → no alarm", async () => {
    await createTag("tag-in", FENCE_WKT);
    const r = await app.inject({
      method: "POST", url: "/smarttags/tag-in/ping", headers: auth,
      payload: { lat: 40.7484, lng: -73.9857, battery: 80 },
    });
    expect(r.statusCode).toBe(200);
    expect(r.json().alarms).toHaveLength(0);
    const alarms = await prisma.geofenceAlarm.count();
    expect(alarms).toBe(0);
  });

  it("outside fence → OUT_OF_GEOFENCE alarm + audit row", async () => {
    await createTag("tag-out", FENCE_WKT);
    const r = await app.inject({
      method: "POST", url: "/smarttags/tag-out/ping", headers: auth,
      payload: { lat: 41.0, lng: -73.0, battery: 80 },
    });
    expect(r.statusCode).toBe(200);
    const body = r.json();
    expect(body.alarmReasons).toContain("OUT_OF_GEOFENCE");

    const alarm = await prisma.geofenceAlarm.findFirst({ where: { tagId: "tag-out" } });
    expect(alarm).not.toBeNull();
    expect(alarm?.reason).toBe("OUT_OF_GEOFENCE");

    const audit = await prisma.auditLog.findFirst({
      where: { action: "GEOFENCE_ALARM", entityType: "GeofenceAlarm" },
    });
    expect(audit).not.toBeNull();
  });

  it("low battery emits LOW_BATTERY alarm in addition to geofence checks", async () => {
    await createTag("tag-batt", FENCE_WKT);
    const r = await app.inject({
      method: "POST", url: "/smarttags/tag-batt/ping", headers: auth,
      payload: { lat: 40.7484, lng: -73.9857, battery: 5 },
    });
    expect(r.json().alarmReasons).toEqual(["LOW_BATTERY"]);
  });

  it("alarms surface through /sync/pull (geofence_alarms table)", async () => {
    await createTag("tag-pull", FENCE_WKT);
    await app.inject({
      method: "POST", url: "/smarttags/tag-pull/ping", headers: auth,
      payload: { lat: 41.0, lng: -73.0 },
    });
    const pull = await app.inject({
      method: "POST", url: "/sync/pull", headers: auth, payload: { lastPulledRev: 0 },
    });
    const arr = pull.json().changes.geofence_alarms.created;
    expect(arr.length).toBe(1);
    expect(arr[0]).toMatchObject({ tag_id: "tag-pull", reason: "OUT_OF_GEOFENCE" });
  });

  it("resolve endpoint sets resolvedAt", async () => {
    await createTag("tag-res", FENCE_WKT);
    const ping = await app.inject({
      method: "POST", url: "/smarttags/tag-res/ping", headers: auth,
      payload: { lat: 41.0, lng: -73.0 },
    });
    const alarmId = ping.json().alarms[0];

    const r = await app.inject({
      method: "POST", url: `/smarttags/alarms/${alarmId}/resolve`, headers: auth,
    });
    expect(r.statusCode).toBe(200);
    const a = await prisma.geofenceAlarm.findUnique({ where: { id: alarmId } });
    expect(a?.resolvedAt).not.toBeNull();
  });

  it("404 for unknown tag", async () => {
    const r = await app.inject({
      method: "POST", url: "/smarttags/missing/ping", headers: auth,
      payload: { lat: 0, lng: 0 },
    });
    expect(r.statusCode).toBe(404);
  });
});
