import { z } from "zod";

const Schema = z.object({
  NODE_ENV: z.enum(["development", "test", "production"]).default("development"),
  PORT: z.coerce.number().int().positive().default(4000),
  DATABASE_URL: z.string().url(),
  SYNC_TOKEN: z.string().min(8).default("dev-sync-token-change-me"),
  JWT_SECRET: z.string().min(16).default("dev-jwt-secret-change-me-at-least-16-chars"),
  JWT_EXPIRES_IN: z.string().default("12h"),
  RATE_LIMIT_PER_MIN: z.coerce.number().int().positive().default(600),
  S3_ENDPOINT: z.string().url().optional(),
  S3_ACCESS_KEY: z.string().optional(),
  S3_SECRET_KEY: z.string().optional(),
  S3_BUCKET_TILES: z.string().default("bargrid-tiles"),
  S3_BUCKET_MEDIA: z.string().default("inventory-media"),
  S3_BUCKET_AUDIT: z.string().default("audit-archive"),
  PULL_PAGE_SIZE: z.coerce.number().int().positive().max(10_000).default(1000),
});

export const env = Schema.parse(process.env);
export type Env = z.infer<typeof Schema>;
