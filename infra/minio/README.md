# MinIO bootstrap

The `minio-bootstrap` service in `docker-compose.yml` runs once on stack
startup and creates these buckets via `mc`:

| Bucket            | Purpose                                                    | Public? |
|-------------------|------------------------------------------------------------|---------|
| `bargrid-tiles`   | Pre-rendered SVG/PNG heatmap tiles served to the Flutter UI| Yes (download-only) |
| `inventory-media` | Photos / docs attached to InventoryItem rows               | No      |
| `audit-archive`   | Cold-storage exports of `audit_logs` for compliance        | No      |

If the bootstrap container fails (rare — usually a stale credential), recreate
buckets manually:

```sh
docker compose run --rm --entrypoint sh minio-bootstrap -lc '
  mc alias set local http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" &&
  mc mb -p local/bargrid-tiles local/inventory-media local/audit-archive &&
  mc anonymous set download local/bargrid-tiles
'
```

Console: <http://localhost:9001> (credentials = `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD`).
