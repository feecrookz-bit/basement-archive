import Fastify from "fastify";
import cors from "@fastify/cors";
import rateLimit from "@fastify/rate-limit";
import { env } from "./env.js";
import { prisma } from "./prisma.js";
import { healthRoutes } from "./routes/health.js";
import { syncRoutes } from "./routes/sync.js";
import { safetyRoutes } from "./routes/safety.js";
import { authRoutes } from "./routes/auth.js";
import { heatmapRoutes } from "./routes/heatmap.js";
import { smartTagRoutes } from "./routes/smarttags.js";
import { matchControlRoutes } from "./routes/matchcontrol.js";

export async function buildApp() {
  const app = Fastify({
    logger: env.NODE_ENV === "test"
      ? false
      : {
          level: env.NODE_ENV === "development" ? "info" : "warn",
          // Pino's JSON output is the structured-log story for Sprint 10 monitoring.
          redact: { paths: ['req.headers.authorization', 'req.headers.cookie'], remove: true },
        },
    bodyLimit: 16 * 1024 * 1024,
    trustProxy: env.NODE_ENV === "production",
  });

  await app.register(cors, { origin: true });

  // Rate limit applied globally; SSE/event streams skip the limiter.
  await app.register(rateLimit, {
    max: env.RATE_LIMIT_PER_MIN,
    timeWindow: "1 minute",
    skipOnError: false,
    allowList: (req) => req.url === "/events" || req.url === "/healthz",
  });

  app.setErrorHandler((err, _req, reply) => {
    app.log.error({ err }, "request_failed");
    const status = (err as { statusCode?: number }).statusCode ?? 500;
    reply.code(status).send({ error: err.message ?? "internal_error" });
  });

  await app.register(healthRoutes);
  await app.register(authRoutes);
  await app.register(syncRoutes);
  await app.register(safetyRoutes);
  await app.register(heatmapRoutes);
  await app.register(smartTagRoutes);
  await app.register(matchControlRoutes);

  app.addHook("onClose", async () => {
    await prisma.$disconnect();
  });

  return app;
}

const isDirectRun = import.meta.url === `file://${process.argv[1]}`
  || import.meta.url.endsWith(process.argv[1] ?? "");

if (isDirectRun) {
  const app = await buildApp();
  try {
    await app.listen({ host: "0.0.0.0", port: env.PORT });
    app.log.info(`basement-backend listening on :${env.PORT}`);
  } catch (err) {
    app.log.error(err);
    process.exit(1);
  }
}
