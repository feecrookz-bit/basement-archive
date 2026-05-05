import type { PrismaClient } from "@prisma/client";
import { emitAudit } from "../audit.js";
import { fromWire, TABLE_BY_WIRE, type TableSpec } from "./tables.js";
import { softDeleteBarGrid, upsertBarGrid } from "./geometry.js";

export interface PushPayload {
  changes: {
    [wireTable: string]: {
      created?: Record<string, unknown>[];
      updated?: Record<string, unknown>[];
      deleted?: string[];
    };
  };
}

export interface PushOptions {
  actorId?: string;
  actorRole?: string;
  ip?: string;
  userAgent?: string;
}

export interface PushResult {
  /** New high-water mark after the push (max serverRev across all writes). */
  timestamp: number;
  applied: { table: string; created: number; updated: number; deleted: number }[];
}

export async function runPush(
  prisma: PrismaClient,
  payload: PushPayload,
  opts: PushOptions,
): Promise<PushResult> {
  const applied: PushResult["applied"] = [];

  await prisma.$transaction(async (tx) => {
    for (const [wire, change] of Object.entries(payload.changes ?? {})) {
      const spec = TABLE_BY_WIRE.get(wire);
      if (!spec) {
        throw Object.assign(new Error(`unknown table: ${wire}`), { statusCode: 400 });
      }

      const created = change.created ?? [];
      const updated = change.updated ?? [];
      const deleted = change.deleted ?? [];

      for (const row of [...created, ...updated]) {
        await applyUpsert(tx as unknown as PrismaClient, spec, row);
      }
      for (const id of deleted) {
        await applyDelete(tx as unknown as PrismaClient, spec, id);
      }

      applied.push({ table: wire, created: created.length, updated: updated.length, deleted: deleted.length });
    }

    await emitAudit(tx as unknown as PrismaClient, {
      action: "SYNC_PUSH",
      entityType: "Sync",
      actorId: opts.actorId,
      actorRole: opts.actorRole,
      ip: opts.ip,
      userAgent: opts.userAgent,
      after: { applied },
    });
  });

  // Read back the global high-water mark from the shared sequence.
  const [{ rev }] = await prisma.$queryRaw<{ rev: bigint }[]>`SELECT last_value AS rev FROM server_rev_seq`;
  return { timestamp: Number(rev), applied };
}

async function applyUpsert(
  prisma: PrismaClient,
  spec: TableSpec,
  rowWire: Record<string, unknown>,
): Promise<void> {
  if (typeof rowWire.id !== "string") {
    throw Object.assign(new Error(`row in ${spec.wire} missing id`), { statusCode: 400 });
  }

  if (spec.raw === "bar_grid_nodes") {
    const lat = Number(rowWire.lat);
    const lng = Number(rowWire.lng);
    if (!Number.isFinite(lat) || !Number.isFinite(lng)) {
      throw Object.assign(new Error("bar_grid_nodes row needs numeric lat/lng"), { statusCode: 400 });
    }
    await upsertBarGrid(prisma, {
      id: rowWire.id,
      gridX: Number(rowWire.grid_x),
      gridY: Number(rowWire.grid_y),
      status: typeof rowWire.status === "string" ? rowWire.status : undefined,
      heatValue: typeof rowWire.heat_value === "number" ? rowWire.heat_value : undefined,
      metadata: rowWire.metadata,
      lat,
      lng,
    });
    return;
  }

  const data = fromWire(spec, rowWire);
  // Strip id from the update side so we don't try to mutate the PK.
  const { id: _id, ...updateData } = data as { id?: string } & Record<string, unknown>;

  const delegate = (prisma as unknown as Record<string, {
    upsert: (args: { where: { id: string }; create: unknown; update: unknown }) => Promise<unknown>;
  }>)[spec.delegate];

  await delegate.upsert({
    where: { id: rowWire.id },
    create: data,
    update: updateData,
  });
}

async function applyDelete(prisma: PrismaClient, spec: TableSpec, id: string): Promise<void> {
  if (spec.raw === "bar_grid_nodes") {
    await softDeleteBarGrid(prisma, id);
    return;
  }
  const delegate = (prisma as unknown as Record<string, {
    update: (args: { where: { id: string }; data: unknown }) => Promise<unknown>;
  }>)[spec.delegate];
  await delegate.update({ where: { id }, data: { deletedAt: new Date() } });
}
