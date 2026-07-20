"""Config loading + versioning.

Every threshold lives in config.yaml — nothing is hardcoded in module code.
Each load is hashed; when a DB pool is available the version is snapshotted
into config_versions and its id is attached to every downstream artifact
(regime snapshots, proposals, trades), so any decision can be reproduced
under the exact config that made it.
"""
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import yaml

DEFAULT_PATH = Path(os.getenv("SENTINEL_CONFIG", "config.yaml"))


class Config:
    """Dot/bracket access over the parsed YAML tree, read-only by convention."""

    def __init__(self, tree: dict, content_hash: str, path: Path | None = None):
        self._tree = tree
        self.content_hash = content_hash
        self.path = path
        self.version_id: int | None = None  # set after DB snapshot

    def get(self, dotted: str, default: Any = None) -> Any:
        node: Any = self._tree
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def __getitem__(self, key: str) -> Any:
        val = self.get(key)
        if val is None:
            raise KeyError(key)
        return val

    def as_dict(self) -> dict:
        return self._tree


def load(path: Path | str = DEFAULT_PATH) -> Config:
    path = Path(path)
    tree = yaml.safe_load(path.read_text()) or {}
    canonical = json.dumps(tree, sort_keys=True, default=str)
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    return Config(tree, digest, path)


async def snapshot(pool, cfg: Config) -> int:
    """Persist this config version (idempotent on hash); returns version id."""
    async with pool.acquire() as con:
        vid = await con.fetchval(
            """
            INSERT INTO config_versions (content, content_hash)
            VALUES ($1::jsonb, $2)
            ON CONFLICT (content_hash) DO UPDATE SET content_hash = EXCLUDED.content_hash
            RETURNING id
            """,
            json.dumps(cfg.as_dict(), default=str), cfg.content_hash,
        )
    cfg.version_id = vid
    return vid
