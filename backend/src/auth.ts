import type { FastifyReply, FastifyRequest } from "fastify";
import type { UserRole } from "@prisma/client";
import { env } from "./env.js";
import { verifyToken } from "./jwt.js";

declare module "fastify" {
  interface FastifyRequest {
    actorId?: string;
    actorRole?: string;
    actorEmail?: string;
    isService?: boolean;
  }
}

// Hybrid auth: accepts either a JWT (for human users) or the SYNC_TOKEN
// (for the Flutter sync client / service callers). Sprint 3 adds JWT;
// Sprint 2's bearer service token still works so unattended sync clients
// don't need a per-device login.
export async function requireAuth(req: FastifyRequest, reply: FastifyReply): Promise<void> {
  const header = req.headers.authorization ?? "";
  const [scheme, token] = header.split(" ", 2);

  if (scheme !== "Bearer" || !token) {
    reply.code(401).send({ error: "unauthorized" });
    return;
  }

  // Service token short-circuit.
  if (token === env.SYNC_TOKEN) {
    req.actorId = (req.headers["x-actor-id"] as string | undefined) ?? "service:sync";
    req.actorRole = "OPERATOR"; // service callers act with OPERATOR rights — never ADMIN.
    req.isService = true;
    return;
  }

  // JWT path.
  try {
    const payload = verifyToken(token);
    req.actorId = payload.sub;
    req.actorRole = payload.role;
    req.actorEmail = payload.email;
    req.isService = false;
  } catch {
    reply.code(401).send({ error: "invalid_token" });
  }
}

const ROLE_RANK: Record<UserRole | string, number> = {
  VIEWER: 0,
  OPERATOR: 1,
  ADMIN: 2,
};

export function requireRole(minRole: UserRole) {
  const min = ROLE_RANK[minRole] ?? 0;
  return async (req: FastifyRequest, reply: FastifyReply): Promise<void> => {
    if (!req.actorRole) {
      reply.code(401).send({ error: "unauthorized" });
      return;
    }
    const have = ROLE_RANK[req.actorRole] ?? -1;
    if (have < min) {
      reply.code(403).send({ error: "forbidden", need: minRole, have: req.actorRole });
    }
  };
}
