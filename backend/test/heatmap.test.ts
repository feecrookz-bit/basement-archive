import { afterAll, beforeEach, describe, expect, it } from "vitest";
import { auth, makeApp, resetDb } from "./helpers.js";
import { prisma } from "../src/prisma.js";

const app = await makeApp();
afterAll(async () => { await app.close(); await prisma.$disconnect(); });
beforeEach(async () => { await resetDb(); });

describe("GET /bargrid/heatmap.svg", () => {
  it("renders a 3x3 grid of cells with one fault", async () => {
    const created = [];
    for (let y = 0; y < 3; y++) {
      for (let x = 0; x < 3; x++) {
        created.push({
          id: `node-${x}-${y}`,
          grid_x: x, grid_y: y,
          status: x === 1 && y === 1 ? "FAULT" : "ACTIVE",
          heat_value: (x + y) / 4,
          lat: 40 + y * 0.001,
          lng: -73 + x * 0.001,
        });
      }
    }
    await app.inject({
      method: "POST", url: "/sync/push", headers: auth,
      payload: { changes: { bar_grid_nodes: { created } } },
    });

    const r = await app.inject({
      method: "GET", url: "/bargrid/heatmap.svg?cell=20", headers: auth,
    });
    expect(r.statusCode).toBe(200);
    expect(r.headers["content-type"]).toContain("image/svg+xml");
    const svg = r.body;
    // 9 cells = 9 <rect …> elements (plus 1 background = 10)
    expect((svg.match(/<rect /g) ?? []).length).toBe(10);
    expect(svg).toContain("ef4444");                 // FAULT red
    expect(svg).toContain("BarGrid heatmap");
  });

  it("returns auth-protected", async () => {
    const r = await app.inject({ method: "GET", url: "/bargrid/heatmap.svg" });
    expect(r.statusCode).toBe(401);
  });
});
