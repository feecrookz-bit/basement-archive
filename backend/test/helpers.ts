import { buildApp } from "../src/server.js";
import { prisma } from "../src/prisma.js";
import { env } from "../src/env.js";
import { hashPassword } from "../src/password.js";
import { signToken } from "../src/jwt.js";
import type { UserRole } from "@prisma/client";

export const TOKEN = env.SYNC_TOKEN;

export async function makeApp() {
  const app = await buildApp();
  await app.ready();
  return app;
}

// Service-token bearer (legacy / unattended sync clients).
export const auth = { authorization: `Bearer ${TOKEN}` };

// Mint a JWT bearer for the given role without hitting /auth/login.
export function jwtAuth(role: UserRole, sub = `user-${role.toLowerCase()}`, email = `${role.toLowerCase()}@test.local`) {
  const token = signToken({ sub, email, role, displayName: role });
  return { authorization: `Bearer ${token}` };
}

export async function resetDb(): Promise<void> {
  await prisma.$executeRawUnsafe(`
    TRUNCATE
      "geofence_alarms",
      "safety_transitions",
      "safety_gateways",
      "inventory_movements",
      "inventory_items",
      "smart_tags",
      "bar_grid_nodes",
      "audit_logs",
      "users"
    RESTART IDENTITY CASCADE
  `);
}

export async function currentRev(): Promise<number> {
  const [{ rev }] = await prisma.$queryRaw<{ rev: bigint }[]>`SELECT last_value AS rev FROM server_rev_seq`;
  return Number(rev);
}

export async function createUser(opts: { email: string; password: string; role: UserRole; displayName?: string }) {
  const hash = await hashPassword(opts.password);
  return prisma.user.create({
    data: {
      email: opts.email.toLowerCase(),
      passwordHash: hash,
      role: opts.role,
      displayName: opts.displayName ?? null,
    },
  });
}
