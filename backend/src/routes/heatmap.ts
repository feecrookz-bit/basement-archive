import type { FastifyInstance } from "fastify";
import { z } from "zod";
import { prisma } from "../prisma.js";
import { requireAuth } from "../auth.js";

const Query = z.object({
  cell: z.coerce.number().int().min(4).max(64).default(20),
  pad:  z.coerce.number().int().min(0).max(64).default(2),
});

interface GridCell {
  gridX: number;
  gridY: number;
  status: string;
  heatValue: number;
}

// Server-rendered SVG so any client (Flutter, browser, Slack preview) can
// embed the heatmap without parsing Bar Grid data themselves.
export async function heatmapRoutes(app: FastifyInstance): Promise<void> {
  app.get("/bargrid/heatmap.svg", { onRequest: [requireAuth] }, async (req, reply) => {
    const q = Query.parse(req.query);
    const cell = q.cell;
    const pad = q.pad;

    const rows = await prisma.$queryRaw<GridCell[]>`
      SELECT "gridX", "gridY", status::text AS status, "heatValue"
        FROM bar_grid_nodes
       WHERE "deletedAt" IS NULL
       ORDER BY "gridX", "gridY"
    `;

    const minX = rows.length ? Math.min(...rows.map(r => r.gridX)) : 0;
    const minY = rows.length ? Math.min(...rows.map(r => r.gridY)) : 0;
    const maxX = rows.length ? Math.max(...rows.map(r => r.gridX)) : 0;
    const maxY = rows.length ? Math.max(...rows.map(r => r.gridY)) : 0;
    const cols = maxX - minX + 1;
    const rowsCount = maxY - minY + 1;
    const w = cols * cell + pad * 2;
    const h = rowsCount * cell + pad * 2;

    const escape = (s: string) => s.replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;" }[c] as string));

    const cells = rows.map(r => {
      const x = (r.gridX - minX) * cell + pad;
      const y = (r.gridY - minY) * cell + pad;
      const fill = colorFor(r.heatValue, r.status);
      return `<rect x="${x}" y="${y}" width="${cell - 1}" height="${cell - 1}" fill="${fill}">`
        + `<title>${escape(`(${r.gridX},${r.gridY}) ${r.status} h=${r.heatValue.toFixed(2)}`)}</title>`
        + `</rect>`;
    }).join("");

    const svg =
      `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" `
      + `role="img" aria-label="BarGrid heatmap">`
      + `<rect width="100%" height="100%" fill="#0f172a"/>`
      + cells
      + `</svg>`;

    reply
      .header("content-type", "image/svg+xml; charset=utf-8")
      .header("cache-control", "no-store");
    return svg;
  });
}

// Status overrides palette (FAULT red, OFFLINE gray, RAIN_DELAYED blue).
// Otherwise interpolate heatValue across a viridis-ish gradient.
function colorFor(heat: number, status: string): string {
  if (status === "FAULT")        return "#ef4444";
  if (status === "OFFLINE")      return "#475569";
  if (status === "RAIN_DELAYED") return "#3b82f6";
  const h = Math.max(0, Math.min(1, heat));
  // Interpolate between dark teal (cold) and amber (hot).
  const cold = [16, 78, 95];
  const hot = [251, 191, 36];
  const r = Math.round(cold[0] + (hot[0] - cold[0]) * h);
  const g = Math.round(cold[1] + (hot[1] - cold[1]) * h);
  const b = Math.round(cold[2] + (hot[2] - cold[2]) * h);
  return `rgb(${r},${g},${b})`;
}
