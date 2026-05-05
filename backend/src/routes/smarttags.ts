import { randomUUID } from "node:crypto";
import type { FastifyInstance } from "fastify";
import { z } from "zod";
import type { AlarmReason } from "@prisma/client";
import { prisma } from "../prisma.js";
import { requireAuth } from "../auth.js";
import { emitAudit } from "../audit.js";
import { bus } from "../events.js";

const PingBody = z.object({
  lat: z.number().min(-90).max(90),
  lng: z.number().min(-180).max(180),
  battery: z.number().int().min(0).max(100).optional(),
});

interface ContainsResult { inside: boolean }

const LOW_BATTERY_THRESHOLD = 15;

export async function smartTagRoutes(app: FastifyInstance): Promise<void> {
  app.addHook("onRequest", requireAuth);

  // POST /smarttags/:id/ping — accept a heartbeat ping, evaluate geofence + battery.
  app.post("/smarttags/:id/ping", async (req, reply) => {
    const id = (req.params as { id: string }).id;
    const parsed = PingBody.safeParse(req.body);
    if (!parsed.success) {
      reply.code(400);
      return { error: "bad_request", issues: parsed.error.issues };
    }
    const { lat, lng, battery } = parsed.data;

    const tag = await prisma.smartTag.findUnique({ where: { id } });
    if (!tag) {
      reply.code(404);
      return { error: "not_found" };
    }

    // Compute alarms before touching the tag, so the audit log captures pre-state.
    const alarms: { reason: AlarmReason; lat: number; lng: number }[] = [];

    if (tag.geofenceWkt) {
      const result = await prisma.$queryRaw<ContainsResult[]>`
        SELECT ST_Contains(
          ST_GeomFromText(${tag.geofenceWkt}, 4326),
          ST_SetSRID(ST_MakePoint(${lng}, ${lat}), 4326)
        ) AS inside
      `;
      if (!result[0]?.inside) {
        alarms.push({ reason: "OUT_OF_GEOFENCE", lat, lng });
      }
    }
    if (typeof battery === "number" && battery < LOW_BATTERY_THRESHOLD) {
      alarms.push({ reason: "LOW_BATTERY", lat, lng });
    }

    const now = new Date();
    await prisma.smartTag.update({
      where: { id },
      data: {
        lastSeenAt: now,
        ...(typeof battery === "number" ? { battery } : {}),
      },
    });

    const alarmIds: string[] = [];
    for (const a of alarms) {
      const alarmId = randomUUID();
      alarmIds.push(alarmId);
      await prisma.geofenceAlarm.create({
        data: { id: alarmId, tagId: id, lat: a.lat, lng: a.lng, reason: a.reason },
      });
      await emitAudit(prisma, {
        action: "GEOFENCE_ALARM",
        entityType: "GeofenceAlarm",
        entityId: alarmId,
        actorId: req.actorId,
        actorRole: req.actorRole,
        ip: req.ip,
        userAgent: req.headers["user-agent"] ?? undefined,
        after: { tagId: id, reason: a.reason, lat: a.lat, lng: a.lng },
      });
      bus.emitEvent({
        type: "geofence.alarm",
        at: now.toISOString(),
        data: { id: alarmId, tagId: id, reason: a.reason, lat: a.lat, lng: a.lng },
      });
    }

    await emitAudit(prisma, {
      action: "TAG_PING",
      entityType: "SmartTag",
      entityId: id,
      actorId: req.actorId,
      actorRole: req.actorRole,
      ip: req.ip,
      userAgent: req.headers["user-agent"] ?? undefined,
      after: { lat, lng, battery: battery ?? null, alarms: alarms.map(a => a.reason) },
    });

    return { tagId: id, alarms: alarmIds, alarmReasons: alarms.map(a => a.reason) };
  });

  // POST /smarttags/alarms/:id/resolve
  app.post("/smarttags/alarms/:id/resolve", async (req, reply) => {
    const id = (req.params as { id: string }).id;
    const a = await prisma.geofenceAlarm.findUnique({ where: { id } });
    if (!a) {
      reply.code(404);
      return { error: "not_found" };
    }
    if (a.resolvedAt) return { id, resolvedAt: a.resolvedAt.toISOString(), already: true };
    const updated = await prisma.geofenceAlarm.update({
      where: { id }, data: { resolvedAt: new Date() },
    });
    return { id, resolvedAt: updated.resolvedAt!.toISOString() };
  });
}
