import type { FastifyInstance } from "fastify";
import { prisma } from "../prisma.js";

export async function healthRoutes(app: FastifyInstance): Promise<void> {
  app.get("/healthz", async () => ({ status: "ok" }));

  app.get("/readyz", async (_req, reply) => {
    try {
      const [{ rev }] = await prisma.$queryRaw<{ rev: bigint }[]>`SELECT last_value AS rev FROM server_rev_seq`;
      return { status: "ready", server_rev: Number(rev) };
    } catch (err) {
      reply.code(503);
      return { status: "not-ready", error: (err as Error).message };
    }
  });
}
