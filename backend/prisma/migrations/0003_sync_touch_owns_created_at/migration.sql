-- Make sync_touch() server-authoritative for both createdAt AND updatedAt.
--
-- Why: Prisma's @default(now()) generates createdAt client-side (new Date())
-- and ships it in the INSERT, while the BEFORE INSERT trigger sets updatedAt
-- := now() server-side. Network latency made the two timestamps drift, so the
-- pull resolver's "createdAt == updatedAt → created bucket" rule was non-
-- deterministic across tables (BarGrid was fine because it uses raw SQL).
--
-- Now the trigger overwrites NEW.createdAt on INSERT with the same now() it
-- assigns to NEW.updatedAt, so they're guaranteed identical within a single
-- transaction. UPDATE leaves createdAt alone.

CREATE OR REPLACE FUNCTION sync_touch() RETURNS trigger AS $$
DECLARE _now timestamp(3) := now();
BEGIN
  IF TG_OP = 'INSERT' THEN
    NEW."createdAt" := _now;
  END IF;
  NEW."updatedAt" := _now;
  NEW."serverRev" := nextval('server_rev_seq');
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
