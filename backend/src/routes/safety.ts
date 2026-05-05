import { randomUUID } from "node:crypto";
import type { FastifyInstance } from "fastify";
import { z } from "zod";
import type { SafetyState } from "@prisma/client";
import { prisma } from "../prisma.js";
import { requireAuth, requireRole } from "../auth.js";
import { emitAudit } from "../audit.js";

const StateEnum = z.enum(["ARMED", "DISARMED", "ESTOP", "RAIN_DELAY", "MATCH_INTERVAL"]);

const TransitionBody = z.object({
  toState: StateEnum,
  reason: z.string().max(500).optional(),
  rainDelayUntil: z.string().datetime().optional(),
  intervalUntil: z.string().datetime().optional(),
  expectedFromState: StateEnum.optional(),
});

// Server-authoritative SafetyGateway transitions. Sync push won't touch safety_gateways.state
// directly — clients call this endpoint, which records a transition row and bumps the gateway.
export async function safetyRoutes(app: FastifyInstance): Promise<void> {
  app.addHook("onRequest", requireAuth);
  app.addHook("onRequest", requireRole("OPERATOR"));

  app.post("/safety/:id/transition", async (req, reply) => {
    const id = (req.params as { id: string }).id;
    const parsed = TransitionBody.safeParse(req.body);
    if (!parsed.success) {
      reply.code(400);
      return { error: "bad_request", issues: parsed.error.issues };
    }

    return prisma.$transaction(async (tx) => {
      const gw = await tx.safetyGateway.findUnique({ where: { id } });
      if (!gw) {
        reply.code(404);
        return { error: "not_found" };
      }

      if (parsed.data.expectedFromState && gw.state !== parsed.data.expectedFromState) {
        reply.code(409);
        return { error: "stale_state", currentState: gw.state };
      }

      const fromState = gw.state;
      const toState = parsed.data.toState as SafetyState;

      await tx.safetyTransition.create({
        data: {
          id: randomUUID(),
          gatewayId: id,
          fromState,
          toState,
          actorId: req.actorId,
          reason: parsed.data.reason ?? null,
        },
      });

      const updated = await tx.safetyGateway.update({
        where: { id },
        data: {
          state: toState,
          rainDelayUntil: parsed.data.rainDelayUntil ? new Date(parsed.data.rainDelayUntil) : null,
          intervalUntil: parsed.data.intervalUntil ? new Date(parsed.data.intervalUntil) : null,
          reason: parsed.data.reason ?? null,
          setByActorId: req.actorId ?? null,
        },
      });

      const action =
        toState === "RAIN_DELAY" ? "RAIN_DELAY_SET"
        : (fromState === "RAIN_DELAY" && toState !== "RAIN_DELAY") ? "RAIN_DELAY_CLEAR"
        : toState === "MATCH_INTERVAL" ? "MATCH_INTERVAL_SET"
        : "SAFETY_OVERRIDE";

      await emitAudit(tx, {
        action,
        entityType: "SafetyGateway",
        entityId: id,
        actorId: req.actorId,
        actorRole: req.actorRole,
        before: { state: fromState },
        after: { state: toState, reason: parsed.data.reason ?? null },
        ip: req.ip,
        userAgent: req.headers["user-agent"] ?? undefined,
      });

      return {
        id,
        fromState,
        toState,
        serverRev: Number(updated.serverRev),
      };
    });
  });
}
