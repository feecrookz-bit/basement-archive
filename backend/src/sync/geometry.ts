import type { Prisma, PrismaClient } from "@prisma/client";

type Tx = PrismaClient | Prisma.TransactionClient;

export interface BarGridRow {
  id: string;
  gridX: number;
  gridY: number;
  status: string;
  heatValue: number;
  metadata: unknown;
  createdAt: Date;
  updatedAt: Date;
  deletedAt: Date | null;
  serverRev: bigint;
  lat: number | null;
  lng: number | null;
}

export interface BarGridWrite {
  id: string;
  gridX: number;
  gridY: number;
  status?: string;
  heatValue?: number;
  metadata?: unknown;
  lat: number;
  lng: number;
  deletedAt?: Date | null;
}

// Pull rows whose serverRev > cursor. Geography is decomposed to {lat, lng} for the wire.
export async function pullBarGrid(
  tx: Tx,
  cursor: bigint,
  limit: number,
): Promise<BarGridRow[]> {
  return tx.$queryRaw<BarGridRow[]>`
    SELECT
      id,
      "gridX", "gridY",
      status::text     AS status,
      "heatValue",
      metadata,
      "createdAt", "updatedAt", "deletedAt",
      "serverRev",
      ST_Y(location::geometry) AS lat,
      ST_X(location::geometry) AS lng
    FROM bar_grid_nodes
    WHERE "serverRev" > ${cursor}
    ORDER BY "serverRev" ASC
    LIMIT ${limit}
  `;
}

// Upsert a BarGridNode. Geography rebuilt from {lat, lng}; trigger bumps serverRev.
export async function upsertBarGrid(tx: Tx, w: BarGridWrite): Promise<void> {
  const metadataJson = JSON.stringify(w.metadata ?? {});
  await tx.$executeRaw`
    INSERT INTO bar_grid_nodes
      (id, "gridX", "gridY", location, status, "heatValue", metadata, "deletedAt")
    VALUES
      (${w.id}, ${w.gridX}, ${w.gridY},
       ST_SetSRID(ST_MakePoint(${w.lng}, ${w.lat}), 4326)::geography,
       COALESCE(${w.status}::"BarGridStatus", 'IDLE'::"BarGridStatus"),
       COALESCE(${w.heatValue}, 0),
       ${metadataJson}::jsonb,
       ${w.deletedAt ?? null})
    ON CONFLICT (id) DO UPDATE SET
      "gridX"     = EXCLUDED."gridX",
      "gridY"     = EXCLUDED."gridY",
      location    = EXCLUDED.location,
      status      = EXCLUDED.status,
      "heatValue" = EXCLUDED."heatValue",
      metadata    = EXCLUDED.metadata,
      "deletedAt" = EXCLUDED."deletedAt"
  `;
}

export async function softDeleteBarGrid(tx: Tx, id: string): Promise<void> {
  await tx.$executeRaw`UPDATE bar_grid_nodes SET "deletedAt" = now() WHERE id = ${id}`;
}
