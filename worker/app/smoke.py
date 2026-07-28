"""Layer 2 smoke test (Part II §5.5).

Runs ONE ingest cycle against LIVE feeds (no respx mocks) into the local Docker
DB, with `FCE_EMBED_MOCK=false` so the real edge function is exercised. Use this
once before deploy to confirm:
  - the recorded feed cassettes still match reality (feeds haven't changed shape)
  - the real Supabase edge function returns valid 384-dim embeddings
  - end-to-end ingest → embed → cluster works against live data

Run:  make smoke   (or:  FCE_EMBED_MOCK=false python -m app.smoke)

Exits 0 on success, 1 on any failure. Prints a summary you can eyeball.
Does NOT assert clustering quality — that's the §5 fixture test's job. This is
a "does the wiring actually work against the real world" check.
"""

from __future__ import annotations

import asyncio
import sys

import structlog

log = structlog.get_logger()


async def main() -> int:
    # Defensive: refuse to run if the mock is on (that defeats the point).
    from app.settings import get_settings

    settings = get_settings()
    if settings.embed_mock:
        print(
            "ERROR: FCE_EMBED_MOCK=true. Layer 2 smoke needs the REAL edge function.\n"
            "  Set FCE_EMBED_MOCK=false and FCE_EMBEDDING_EDGE_FUNCTION_URL to your\n"
            "  deployed Supabase edge function, then re-run.",
            file=sys.stderr,
        )
        return 1

    from app.cluster import cluster_new_items
    from app.db import close_pool, stats
    from app.ingest import run_all_sources

    print("=== Layer 2 smoke: one cycle against live feeds ===", flush=True)
    summaries = await run_all_sources()
    print("\n--- ingest summaries ---", flush=True)
    for s in summaries:
        print(
            f"  {s['name']:<30} status={s['status']:<8} "
            f"fetched={s.get('fetched', 0)} new={s.get('new', 0)} "
            f"embedded={s.get('embedded', 0)} embed_failures={s.get('embed_failures', 0)}",
            flush=True,
        )

    print("\n--- clustering ---", flush=True)
    cluster_summary = await cluster_new_items()
    print(
        f"  checked={cluster_summary['checked']} merged={cluster_summary['merged']} "
        f"new_stories={cluster_summary['new_stories']} keyword_used={cluster_summary['keyword_used']}",
        flush=True,
    )

    print("\n--- /stats ---", flush=True)
    s = await stats()
    items = s.get("items", {})
    stories = s.get("stories", {})
    print(f"  items: total={items.get('total')} with_embedding={items.get('with_embedding')} "
          f"without_embedding={items.get('without_embedding')} orphaned={items.get('orphaned')}",
          flush=True)
    print(f"  stories: total={stories.get('total')} created_24h={stories.get('created_24h')} "
          f"avg_items_per_story={float(stories.get('avg_items_per_story', 0)):.2f}", flush=True)
    print(f"  embedding_health: {s.get('embedding_health')}", flush=True)

    await close_pool()

    # Soft assertions: surface problems without being brittle.
    problems = []
    if items.get("total", 0) == 0:
        problems.append("no items ingested — feeds may be down or changed shape")
    if items.get("orphaned", 0) > 0:
        problems.append(f"{items['orphaned']} orphaned items — story creation dropped something")
    if s.get("embedding_health") == "degraded":
        problems.append("embedding_health=degraded — edge function may be misconfigured")
    if problems:
        print("\n=== SMOKE COMPLETE WITH PROBLEMS ===", file=sys.stderr)
        for p in problems:
            print(f"  ⚠ {p}", file=sys.stderr)
        return 1
    print("\n=== SMOKE OK ===", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
