import type { FastifyInstance } from "fastify";
import { z } from "zod";
import { prisma } from "../prisma.js";
import { requireAuth } from "../auth.js";
import { emitAudit } from "../audit.js";
import { runPull } from "../sync/pull.js";
import { runPush, type PushPayload } from "../sync/push.js";

const PullBody = z.object({
  lastPulledRev: z.coerce.number().int().nonnegative().default(0),
  schemaVersion: z.number().int().positive().optional(),
});

const PushBody = z.object({
  changes: z.record(z.string(), z.object({
    created: z.array(z.record(z.string(), z.unknown())).optional(),
    updated: z.array(z.record(z.string(), z.unknown())).optional(),
    deleted: z.array(z.string()).optional(),
  })),
  lastPulledRev: z.coerce.number().int().nonnegative().optional(),
});

export async function syncRoutes(app: FastifyInstance): Promise<void> {
  app.addHook("onRequest", requireAuth);

  app.post("/sync/pull", async (req, reply) => {
    const parsed = PullBody.safeParse(req.body);
    if (!parsed.success) {
      reply.code(400);
      return { error: "bad_request", issues: parsed.error.issues };
    }
    const cursor = BigInt(parsed.data.lastPulledRev);
    const result = await runPull(prisma, cursor);

    await emitAudit(prisma, {
      action: "SYNC_PULL",
      entityType: "Sync",
      actorId: req.actorId,
      actorRole: req.actorRole,
      ip: req.ip,
      userAgent: req.headers["user-agent"] ?? undefined,
      after: { from: Number(cursor), to: result.timestamp },
    });

    return result;
  });

  app.post("/sync/push", async (req, reply) => {
    const parsed = PushBody.safeParse(req.body);
    if (!parsed.success) {
      reply.code(400);
      return { error: "bad_request", issues: parsed.error.issues };
    }
    try {
      const result = await runPush(prisma, parsed.data as PushPayload, {
        actorId: req.actorId,
        actorRole: req.actorRole,
        ip: req.ip,
        userAgent: req.headers["user-agent"] ?? undefined,
      });
      return result;
    } catch (err) {
      const e = err as Error & { statusCode?: number };
      reply.code(e.statusCode ?? 500);
      return { error: e.message };
    }
  });
}
