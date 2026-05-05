import type { PrismaClient } from "@prisma/client";
import { env } from "../env.js";
import { SYNCED_TABLES, toWire, type TableSpec } from "./tables.js";
import { pullBarGrid } from "./geometry.js";

export interface PullChanges {
  [table: string]: {
    created: Record<string, unknown>[];
    updated: Record<string, unknown>[];
    deleted: string[];
  };
}

export interface PullResult {
  changes: PullChanges;
  /** New high-water mark the client should send back next time. */
  timestamp: number;
}

// Server emits a row as `created` if createdAt == updatedAt (never updated since insert),
// else `updated`. Soft-deleted rows go in `deleted` with id only.
export async function runPull(prisma: PrismaClient, lastPulledRev: bigint): Promise<PullResult> {
  const changes: PullChanges = {};
  let highWaterMark = lastPulledRev;

  for (const spec of SYNCED_TABLES) {
    const bucket = { created: [] as Record<string, unknown>[], updated: [] as Record<string, unknown>[], deleted: [] as string[] };

    const rows = spec.raw === "bar_grid_nodes"
      ? await pullBarGrid(prisma, lastPulledRev, env.PULL_PAGE_SIZE)
      : await pullGeneric(prisma, spec, lastPulledRev, env.PULL_PAGE_SIZE);

    for (const row of rows) {
      const rev = typeof row.serverRev === "bigint" ? row.serverRev : BigInt(row.serverRev as number);
      if (rev > highWaterMark) highWaterMark = rev;

      if (row.deletedAt) {
        bucket.deleted.push(row.id as string);
        continue;
      }

      const wire = spec.raw === "bar_grid_nodes"
        ? barGridToWire(row as never)
        : toWire(spec, row);

      // Newly created if updatedAt within the same transaction window as createdAt.
      const created =
        row.createdAt instanceof Date && row.updatedAt instanceof Date
          ? row.createdAt.getTime() === row.updatedAt.getTime()
          : false;

      (created ? bucket.created : bucket.updated).push(wire);
    }

    changes[spec.wire] = bucket;
  }

  return { changes, timestamp: Number(highWaterMark) };
}

async function pullGeneric(
  prisma: PrismaClient,
  spec: TableSpec,
  cursor: bigint,
  limit: number,
): Promise<Array<Record<string, unknown> & { id: string; createdAt: Date; updatedAt: Date; deletedAt: Date | null; serverRev: bigint }>> {
  const delegate = (prisma as unknown as Record<string, { findMany: (args: unknown) => Promise<unknown[]> }>)[spec.delegate];
  const rows = (await delegate.findMany({
    where: { serverRev: { gt: cursor } },
    orderBy: { serverRev: "asc" },
    take: limit,
  })) as Array<Record<string, unknown> & { id: string; createdAt: Date; updatedAt: Date; deletedAt: Date | null; serverRev: bigint }>;
  return rows;
}

function barGridToWire(row: {
  id: string;
  gridX: number;
  gridY: number;
  status: string;
  heatValue: number;
  metadata: unknown;
  createdAt: Date;
  updatedAt: Date;
  serverRev: bigint;
  lat: number | null;
  lng: number | null;
}): Record<string, unknown> {
  return {
    id: row.id,
    grid_x: row.gridX,
    grid_y: row.gridY,
    status: row.status,
    heat_value: Number(row.heatValue),
    metadata: row.metadata ?? {},
    lat: row.lat,
    lng: row.lng,
    created_at: row.createdAt.toISOString(),
    updated_at: row.updatedAt.toISOString(),
    server_rev: Number(row.serverRev),
  };
}
