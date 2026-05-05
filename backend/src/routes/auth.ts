import type { FastifyInstance } from "fastify";
import { z } from "zod";
import { prisma } from "../prisma.js";
import { hashPassword, verifyPassword } from "../password.js";
import { signToken } from "../jwt.js";
import { emitAudit } from "../audit.js";
import { requireAuth } from "../auth.js";

const LoginBody = z.object({
  email: z.string().email(),
  password: z.string().min(1),
});

const BootstrapBody = z.object({
  email: z.string().email(),
  password: z.string().min(8),
  displayName: z.string().min(1).max(100).optional(),
});

export async function authRoutes(app: FastifyInstance): Promise<void> {
  // POST /auth/bootstrap-admin — only works when no users exist yet.
  app.post("/auth/bootstrap-admin", async (req, reply) => {
    const parsed = BootstrapBody.safeParse(req.body);
    if (!parsed.success) {
      reply.code(400);
      return { error: "bad_request", issues: parsed.error.issues };
    }
    const count = await prisma.user.count();
    if (count > 0) {
      reply.code(409);
      return { error: "already_bootstrapped" };
    }
    const passwordHash = await hashPassword(parsed.data.password);
    const user = await prisma.user.create({
      data: {
        email: parsed.data.email.toLowerCase(),
        passwordHash,
        displayName: parsed.data.displayName ?? null,
        role: "ADMIN",
      },
    });
    await emitAudit(prisma, {
      action: "USER_BOOTSTRAP",
      entityType: "User",
      entityId: user.id,
      actorId: user.id,
      actorRole: "ADMIN",
      ip: req.ip,
      userAgent: req.headers["user-agent"] ?? undefined,
      after: { email: user.email, role: user.role },
    });
    return { id: user.id, email: user.email, role: user.role };
  });

  // POST /auth/login
  app.post("/auth/login", async (req, reply) => {
    const parsed = LoginBody.safeParse(req.body);
    if (!parsed.success) {
      reply.code(400);
      return { error: "bad_request" };
    }
    const email = parsed.data.email.toLowerCase();
    const user = await prisma.user.findUnique({ where: { email } });

    if (!user || user.disabled) {
      await emitAudit(prisma, {
        action: "LOGIN_FAIL",
        entityType: "User",
        entityId: user?.id,
        ip: req.ip,
        userAgent: req.headers["user-agent"] ?? undefined,
        after: { email, reason: user ? "disabled" : "no_user" },
      });
      reply.code(401);
      return { error: "invalid_credentials" };
    }

    const ok = await verifyPassword(parsed.data.password, user.passwordHash);
    if (!ok) {
      await emitAudit(prisma, {
        action: "LOGIN_FAIL",
        entityType: "User",
        entityId: user.id,
        ip: req.ip,
        userAgent: req.headers["user-agent"] ?? undefined,
        after: { email, reason: "bad_password" },
      });
      reply.code(401);
      return { error: "invalid_credentials" };
    }

    await prisma.user.update({ where: { id: user.id }, data: { lastLogin: new Date() } });

    const token = signToken({
      sub: user.id,
      email: user.email,
      role: user.role,
      displayName: user.displayName ?? undefined,
    });

    await emitAudit(prisma, {
      action: "LOGIN",
      entityType: "User",
      entityId: user.id,
      actorId: user.id,
      actorRole: user.role,
      ip: req.ip,
      userAgent: req.headers["user-agent"] ?? undefined,
    });

    return {
      token,
      user: { id: user.id, email: user.email, role: user.role, displayName: user.displayName },
    };
  });

  // GET /auth/me — auth required.
  app.get("/auth/me", { onRequest: [requireAuth] }, async (req) => {
    return {
      id: req.actorId,
      role: req.actorRole,
      email: req.actorEmail,
      isService: req.isService ?? false,
    };
  });
}
