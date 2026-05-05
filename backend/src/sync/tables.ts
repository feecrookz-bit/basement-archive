// Registry of synced tables. The HTTP layer translates between WatermelonDB-style
// snake_case JSON and the Prisma model's camelCase fields.
//
// `bar_grid_nodes` is special: its `location` column is a PostGIS geography that
// Prisma can't read/write directly, so we go through raw SQL in geometry.ts.

export interface TableSpec {
  /** WatermelonDB / wire table name (snake_case). */
  wire: string;
  /** Prisma delegate name on PrismaClient (camelCase). */
  delegate: PrismaDelegate;
  /** Wire-column → Prisma-field map. `id`, `created_at`, `updated_at`, `server_rev`, `deleted_at` are added automatically. */
  columns: Record<string, string>;
  /** Whether the model has a `serverRev` cursor (vs. append-only audit_logs). */
  synced: true;
  /** Optional adapter for fields Prisma can't represent (e.g. PostGIS). */
  raw?: "bar_grid_nodes";
}

export type PrismaDelegate =
  | "barGridNode"
  | "smartTag"
  | "inventoryItem"
  | "inventoryMovement"
  | "safetyGateway"
  | "safetyTransition"
  | "geofenceAlarm";

export const SYNCED_TABLES: TableSpec[] = [
  {
    wire: "bar_grid_nodes",
    delegate: "barGridNode",
    raw: "bar_grid_nodes",
    columns: {
      grid_x: "gridX",
      grid_y: "gridY",
      // location is handled by geometry.ts — wire shape is { lat, lng }.
      status: "status",
      heat_value: "heatValue",
      metadata: "metadata",
    },
    synced: true,
  },
  {
    wire: "smart_tags",
    delegate: "smartTag",
    columns: {
      node_id: "nodeId",
      external_ref: "externalRef",
      geofence_wkt: "geofenceWkt",
      last_seen_at: "lastSeenAt",
      battery: "battery",
    },
    synced: true,
  },
  {
    wire: "inventory_items",
    delegate: "inventoryItem",
    columns: {
      sku: "sku",
      name: "name",
      quantity: "quantity",
      unit: "unit",
      bin_location: "binLocation",
      media_key: "mediaKey",
      attributes: "attributes",
    },
    synced: true,
  },
  {
    wire: "inventory_movements",
    delegate: "inventoryMovement",
    columns: {
      item_id: "itemId",
      delta: "delta",
      reason: "reason",
      actor_id: "actorId",
      occurred_at: "occurredAt",
    },
    synced: true,
  },
  {
    wire: "safety_gateways",
    delegate: "safetyGateway",
    columns: {
      name: "name",
      state: "state",
      rain_delay_until: "rainDelayUntil",
      interval_until: "intervalUntil",
      last_heartbeat: "lastHeartbeat",
      reason: "reason",
      set_by_actor_id: "setByActorId",
    },
    synced: true,
  },
  {
    wire: "safety_transitions",
    delegate: "safetyTransition",
    columns: {
      gateway_id: "gatewayId",
      from_state: "fromState",
      to_state: "toState",
      actor_id: "actorId",
      reason: "reason",
      occurred_at: "occurredAt",
    },
    synced: true,
  },
  {
    wire: "geofence_alarms",
    delegate: "geofenceAlarm",
    columns: {
      tag_id: "tagId",
      lat: "lat",
      lng: "lng",
      reason: "reason",
      resolved_at: "resolvedAt",
    },
    synced: true,
  },
];

export const TABLE_BY_WIRE = new Map(SYNCED_TABLES.map((t) => [t.wire, t]));

// Convert a Prisma row (camelCase) to wire format (snake_case + numbers).
export function toWire(spec: TableSpec, row: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {
    id: row.id,
    created_at: serializeTs(row.createdAt),
    updated_at: serializeTs(row.updatedAt),
    server_rev: serializeBig(row.serverRev),
  };
  for (const [wire, prismaField] of Object.entries(spec.columns)) {
    out[wire] = serialize(row[prismaField]);
  }
  return out;
}

// Convert wire payload (snake_case) to Prisma input (camelCase).
export function fromWire(spec: TableSpec, payload: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  if (typeof payload.id === "string") out.id = payload.id;
  for (const [wire, prismaField] of Object.entries(spec.columns)) {
    if (wire in payload) out[prismaField] = payload[wire];
  }
  return out;
}

function serialize(v: unknown): unknown {
  if (v instanceof Date) return v.toISOString();
  if (typeof v === "bigint") return Number(v);
  return v;
}
function serializeTs(v: unknown): string | null {
  if (v instanceof Date) return v.toISOString();
  return null;
}
function serializeBig(v: unknown): number {
  if (typeof v === "bigint") return Number(v);
  if (typeof v === "number") return v;
  return 0;
}
