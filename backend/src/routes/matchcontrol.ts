import { randomUUID } from "node:crypto";
import type { FastifyInstance, FastifyRequest } from "fastify";
import { z } from "zod";
import type { SafetyState } from "@prisma/client";
import { prisma } from "../prisma.js";
import { requireAuth, requireRole } from "../auth.js";
import { emitAudit } from "../audit.js";
import { bus, type BasementEvent } from "../events.js";

const RainDelayBody = z.object({
  gatewayId: z.string().min(1),
  durationMinutes: z.number().int().min(1).max(24 * 60),
  reason: z.string().max(500).optional(),
});

const IntervalBody = z.object({
  gatewayId: z.string().min(1),
  durationMinutes: z.number().int().min(1).max(180),
  reason: z.string().max(500).optional(),
});

const ClearBody = z.object({
  gatewayId: z.string().min(1),
  reason: z.string().max(500).optional(),
});

export async function matchControlRoutes(app: FastifyInstance): Promise<void> {
  // POST /matchcontrol/rain-delay — OPERATOR+ only
  app.post(
    "/matchcontrol/rain-delay",
    { onRequest: [requireAuth, requireRole("OPERATOR")] },
    async (req, reply) => {
      const parsed = RainDelayBody.safeParse(req.body);
      if (!parsed.success) {
        reply.code(400);
        return { error: "bad_request", issues: parsed.error.issues };
      }
      return setSafetyState(req, "RAIN_DELAY", {
        gatewayId: parsed.data.gatewayId,
        until: new Date(Date.now() + parsed.data.durationMinutes * 60_000),
        reason: parsed.data.reason ?? null,
        eventType: "rain_delay.set",
      });
    },
  );

  // POST /matchcontrol/interval — OPERATOR+
  app.post(
    "/matchcontrol/interval",
    { onRequest: [requireAuth, requireRole("OPERATOR")] },
    async (req, reply) => {
      const parsed = IntervalBody.safeParse(req.body);
      if (!parsed.success) {
        reply.code(400);
        return { error: "bad_request", issues: parsed.error.issues };
      }
      return setSafetyState(req, "MATCH_INTERVAL", {
        gatewayId: parsed.data.gatewayId,
        until: new Date(Date.now() + parsed.data.durationMinutes * 60_000),
        reason: parsed.data.reason ?? null,
        eventType: "match_interval.set",
      });
    },
  );

  // POST /matchcontrol/clear — return to ARMED. OPERATOR+
  app.post(
    "/matchcontrol/clear",
    { onRequest: [requireAuth, requireRole("OPERATOR")] },
    async (req, reply) => {
      const parsed = ClearBody.safeParse(req.body);
      if (!parsed.success) {
        reply.code(400);
        return { error: "bad_request", issues: parsed.error.issues };
      }
      return setSafetyState(req, "ARMED", {
        gatewayId: parsed.data.gatewayId,
        until: null,
        reason: parsed.data.reason ?? null,
        eventType: "rain_delay.clear",
      });
    },
  );

  // GET /events — SSE stream. Auth required (any user).
  app.get("/events", { onRequest: [requireAuth] }, async (req, reply) => {
    reply.raw.writeHead(200, {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      Connection: "keep-alive",
      "X-Accel-Buffering": "no",
    });
    reply.raw.write(`: connected ${new Date().toISOString()}\n\n`);

    const send = (ev: BasementEvent) => {
      reply.raw.write(`event: ${ev.type}\n`);
      reply.raw.write(`data: ${JSON.stringify({ at: ev.at, ...ev.data })}\n\n`);
    };
    const off = bus.onEvent(send);

    // Heartbeat so reverse proxies don't reap idle connections.
    const beat = setInterval(() => reply.raw.write(`: hb ${Date.now()}\n\n`), 25_000);

    req.raw.on("close", () => {
      clearInterval(beat);
      off();
      reply.raw.end();
    });

    return reply;
  });
}

interface ApplyArgs {
  gatewayId: string;
  until: Date | null;
  reason: string | null;
  eventType: BasementEvent["type"];
}

async function setSafetyState(
  req: FastifyRequest,
  toState: SafetyState,
  args: ApplyArgs,
): Promise<unknown> {
  return prisma.$transaction(async (tx) => {
    const gw = await tx.safetyGateway.findUnique({ where: { id: args.gatewayId } });
    if (!gw) {
      const e = Object.assign(new Error("gateway_not_found"), { statusCode: 404 });
      throw e;
    }
    const fromState = gw.state;

    await tx.safetyTransition.create({
      data: {
        id: randomUUID(),
        gatewayId: args.gatewayId,
        fromState,
        toState,
        actorId: req.actorId,
        reason: args.reason,
      },
    });

    const updated = await tx.safetyGateway.update({
      where: { id: args.gatewayId },
      data: {
        state: toState,
        rainDelayUntil:  toState === "RAIN_DELAY"     ? args.until : null,
        intervalUntil:   toState === "MATCH_INTERVAL" ? args.until : null,
        reason: args.reason,
        setByActorId: req.actorId ?? null,
      },
    });

    const action =
      toState === "RAIN_DELAY"     ? "RAIN_DELAY_SET" :
      toState === "MATCH_INTERVAL" ? "MATCH_INTERVAL_SET" :
      fromState === "RAIN_DELAY"   ? "RAIN_DELAY_CLEAR" :
                                     "SAFETY_OVERRIDE";

    await emitAudit(tx, {
      action,
      entityType: "SafetyGateway",
      entityId: args.gatewayId,
      actorId: req.actorId,
      actorRole: req.actorRole,
      before: { state: fromState },
      after: { state: toState, until: args.until?.toISOString() ?? null },
      ip: req.ip,
      userAgent: req.headers["user-agent"] ?? undefined,
    });

    bus.emitEvent({
      type: args.eventType,
      at: new Date().toISOString(),
      data: {
        gatewayId: args.gatewayId,
        fromState,
        toState,
        until: args.until?.toISOString() ?? null,
        reason: args.reason,
        actorId: req.actorId,
      },
    });

    return {
      gatewayId: args.gatewayId,
      fromState,
      toState,
      until: args.until?.toISOString() ?? null,
      serverRev: Number(updated.serverRev),
    };
  });
}
