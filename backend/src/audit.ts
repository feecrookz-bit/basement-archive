import { randomUUID } from "node:crypto";
import type { Prisma, PrismaClient, AuditAction } from "@prisma/client";

type Tx = PrismaClient | Prisma.TransactionClient;

interface EmitArgs {
  action: AuditAction;
  entityType: string;
  entityId?: string;
  actorId?: string;
  actorRole?: string;
  before?: unknown;
  after?: unknown;
  ip?: string;
  userAgent?: string;
}

// Insert one audit_logs row. The DB trigger fills prevHash + rowHash, so we never set them here.
export async function emitAudit(tx: Tx, args: EmitArgs): Promise<void> {
  await tx.auditLog.create({
    data: {
      id: randomUUID(),
      action: args.action,
      entityType: args.entityType,
      entityId: args.entityId ?? null,
      actorId: args.actorId ?? null,
      actorRole: args.actorRole ?? null,
      before: (args.before ?? null) as Prisma.InputJsonValue,
      after: (args.after ?? null) as Prisma.InputJsonValue,
      ip: args.ip ?? null,
      userAgent: args.userAgent ?? null,
    },
  });
}
