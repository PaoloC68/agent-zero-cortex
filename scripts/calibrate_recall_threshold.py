#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)

_CALIB_CONTENTS: list[str] = [
    # Python async programming
    "Python asyncio event loop manages coroutines and I/O callbacks efficiently",
    "async/await syntax in Python enables non-blocking I/O operations without threads",
    "httpx AsyncClient provides async HTTP requests with connection pooling support",
    "asyncio.gather runs multiple coroutines concurrently and collects results",
    "asyncio.create_task schedules coroutine execution without blocking current context",
    "Python coroutines use yield-based mechanism wrapped by async def and await",
    "asyncio timeout controls can be implemented with asyncio.wait_for wrapper",
    "aiohttp and httpx are popular async HTTP clients for Python web requests",
    "async context managers support __aenter__ and __aexit__ protocol methods",
    "asyncio.sleep is the async equivalent of time.sleep for non-blocking waits",
    # Agent memory systems
    "FAISS vector index stores embeddings for semantic similarity search operations",
    "Reciprocal Rank Fusion combines multiple retrieval signals into unified score",
    "Memory recall threshold filters out low-confidence semantic match results",
    "BM25 text scoring algorithm uses term frequency and inverse document frequency",
    "Hybrid search combines dense vector search with sparse keyword matching",
    "Vector embeddings encode semantic meaning in high-dimensional space",
    "Memory deduplication uses content hashing to prevent duplicate storage",
    "Semantic search retrieves contextually relevant memories beyond keyword matching",
    "Idempotency keys prevent duplicate memory creation on replay or retry",
    "Memory importance scores weight retrieval results for better ranking quality",
    # Cortex API patterns
    "Cortex session creation maps external session IDs to internal tracking",
    "Cortex memory areas include fragments for context and solutions for outcomes",
    "Cortex recall endpoint accepts threshold and limit for result filtering",
    "Cortex API authentication uses Bearer token in Authorization header",
    "Cortex source_project field enables project-scoped memory retrieval",
    "Cortex memory write requires content kind area and optional importance",
    "Cortex idempotent writes use Idempotency-Key header for safe replay",
    "Cortex recall returns id content score source_project and matched_via fields",
    "Cortex sessions endpoint POST creates session and returns session UUID",
    "Cortex topic slugs are lowercase alphanumeric with hyphens and underscores",
    # Docker and container deployment
    "Docker compose defines multi-service applications with environment variables",
    "Proxmox LXC containers provide lightweight virtualization on homelab hardware",
    "Docker exec runs commands inside running containers for management tasks",
    "Environment variables configure containerized services without code changes",
    "Docker volume mounts persist data outside container lifecycle boundaries",
    "Proxmox pct exec runs commands inside LXC container from host machine",
    "Docker container restart policies ensure service availability after failures",
    "Health check endpoints verify service readiness in containerized deployments",
    "Docker logs command streams container stdout and stderr for debugging",
    "Docker compose up force-recreate rebuilds containers with updated configuration",
    # Database and search systems
    "PostgreSQL full-text search uses tsvector and tsquery for keyword matching",
    "pgvector extension enables vector similarity search in PostgreSQL database",
    "Database indexes improve query performance through pre-computed lookup structures",
    "Trigram similarity indexes enable fuzzy string matching in PostgreSQL",
    "Connection pooling reduces database connection overhead in web applications",
    "SQL query planning uses statistics to choose optimal execution strategies",
    "Transaction isolation levels control concurrent read and write visibility",
    "Database vacuuming reclaims space from dead tuples in PostgreSQL tables",
    "Rank fusion algorithms combine multiple retrieval signals by normalizing scores",
    "Vector cosine similarity measures angle between embedding vectors for relevance",
]


def post_memory(
    client: httpx.Client,
    url: str,
    api_key: str,
    content: str,
) -> str | None:
    try:
        resp = client.post(
            f"{url}/v1/memories",
            json={
                "content": content,
                "kind": "fragments",
                "area": "fragments",
                "source_project": "_calibration",
                "importance": 0.5,
            },
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("id") or data.get("memory_id")
    except Exception as exc:
        logger.warning("post_memory failed: %s", exc)
        return None


def recall_query(
    client: httpx.Client,
    url: str,
    api_key: str,
    query: str,
    limit: int = 50,
    legacy_rank: bool = False,
) -> list[dict[str, Any]]:
    try:
        params: dict[str, str] = {}
        if legacy_rank:
            params["legacy_rank"] = "true"
        resp = client.post(
            f"{url}/v1/recall",
            json={"query": query, "threshold": 0.0, "limit": limit},
            params=params,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.warning("recall_query failed for %r: %s", query, exc)
        return []


def forget_memory(
    client: httpx.Client,
    url: str,
    api_key: str,
    memory_id: str,
) -> bool:
    try:
        resp = client.post(
            f"{url}/v1/memories",
            json={"action": "forget", "memory_id": memory_id},
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )
        resp.raise_for_status()
        return True
    except Exception as exc:
        logger.warning("forget_memory %s failed: %s", memory_id, exc)
        return False


def _percentile(sorted_data: list[float], p: float) -> float:
    if not sorted_data:
        return 0.0
    n = len(sorted_data)
    if n == 1:
        return sorted_data[0]
    rank = (p / 100.0) * (n - 1)
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return sorted_data[lower]
    frac = rank - lower
    return sorted_data[lower] * (1.0 - frac) + sorted_data[upper] * frac


def compute_stats(scores: list[float]) -> dict[str, Any]:
    s = sorted(scores)
    return {
        "count": len(s),
        "min": round(s[0], 6) if s else 0.0,
        "p5": round(_percentile(s, 5), 6),
        "p25": round(_percentile(s, 25), 6),
        "p50": round(_percentile(s, 50), 6),
        "p75": round(_percentile(s, 75), 6),
        "p95": round(_percentile(s, 95), 6),
        "max": round(s[-1], 6) if s else 0.0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Cortex recall threshold calibration")
    parser.add_argument(
        "--url",
        default=os.environ.get("CORTEX_URL", "http://192.168.1.12:8001"),
        help="Cortex base URL",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("CORTEX_API_KEY", ""),
        help="Cortex API key",
    )
    parser.add_argument(
        "--queries",
        required=True,
        help="Path to golden-queries.json",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Directory for threshold-recommendation-{date}.json output",
    )
    args = parser.parse_args()

    if not args.api_key:
        logger.error("CORTEX_API_KEY not set")
        sys.exit(1)

    queries_path = Path(args.queries)
    if not queries_path.exists():
        logger.error("Queries file not found: %s", queries_path)
        sys.exit(1)

    golden_queries: list[dict[str, str]] = json.loads(queries_path.read_text())
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    run_uuid = str(uuid.uuid4())
    date_str = datetime.now(tz=timezone.utc).strftime("%Y%m%d-%H%M%S")
    calib_prefix = f"[CALIB-{run_uuid}]"

    logger.info("=== Cortex threshold calibration ===")
    logger.info("Run UUID: %s", run_uuid)
    logger.info("Cortex URL: %s", args.url)
    logger.info("Queries: %d", len(golden_queries))

    memory_ids: list[str] = []

    with httpx.Client() as client:
        logger.info("Step 1: Posting %d calibration memories...", len(_CALIB_CONTENTS))
        for i, raw_content in enumerate(_CALIB_CONTENTS):
            content = f"{calib_prefix} {raw_content}"
            mem_id = post_memory(client, args.url, args.api_key, content)
            if mem_id:
                memory_ids.append(mem_id)
                logger.info("  [%d/%d] id=%s", i + 1, len(_CALIB_CONTENTS), mem_id)
            else:
                logger.warning("  [%d/%d] failed to post memory", i + 1, len(_CALIB_CONTENTS))

        logger.info(
            "Posted %d/%d memories. Waiting 5s for embedding generation...",
            len(memory_ids),
            len(_CALIB_CONTENTS),
        )
        time.sleep(5)

        logger.info("Step 2: Running %d golden queries (standard + legacy_rank)...", len(golden_queries))
        relevant_scores: list[float] = []
        irrelevant_scores: list[float] = []
        relevant_scores_lr: list[float] = []
        irrelevant_scores_lr: list[float] = []

        for entry in golden_queries:
            qid = entry["id"]
            query = entry["query"]
            label = entry["label"]

            results = recall_query(client, args.url, args.api_key, query, limit=50, legacy_rank=False)
            calib_scores = [
                float(r["score"])
                for r in results
                if calib_prefix in r.get("content", "")
            ]
            if label == "relevant":
                relevant_scores.extend(calib_scores)
            else:
                irrelevant_scores.extend(calib_scores)
            logger.info("  [std] %s label=%s calib_hits=%d", qid, label, len(calib_scores))

            results_lr = recall_query(client, args.url, args.api_key, query, limit=50, legacy_rank=True)
            calib_scores_lr = [
                float(r["score"])
                for r in results_lr
                if calib_prefix in r.get("content", "")
            ]
            if label == "relevant":
                relevant_scores_lr.extend(calib_scores_lr)
            else:
                irrelevant_scores_lr.extend(calib_scores_lr)

        logger.info("Step 3: Computing score distribution stats...")
        rel_stats = compute_stats(relevant_scores)
        irr_stats = compute_stats(irrelevant_scores)
        rel_stats_lr = compute_stats(relevant_scores_lr)
        irr_stats_lr = compute_stats(irrelevant_scores_lr)

        logger.info(
            "  [std] relevant  : p5=%.5f  p50=%.5f  p95=%.5f  n=%d",
            rel_stats["p5"], rel_stats["p50"], rel_stats["p95"], rel_stats["count"],
        )
        logger.info(
            "  [std] irrelevant: p5=%.5f  p50=%.5f  p95=%.5f  n=%d",
            irr_stats["p5"], irr_stats["p50"], irr_stats["p95"], irr_stats["count"],
        )

        logger.info("Step 4: Detecting scoring algorithm...")
        all_scores = relevant_scores + irrelevant_scores
        max_score = max(all_scores) if all_scores else 0.0
        if max_score < 0.10:
            scoring_hint = "RRF-like (max<0.10, k=60 hardcoded)"
        elif max_score > 0.20:
            scoring_hint = "composite-like (max>0.20, weighted combination)"
        else:
            scoring_hint = "intermediate (0.10-0.20, algorithm unclear)"
        logger.info("  hint: %s (max_score=%.5f)", scoring_hint, max_score)

        logger.info("Step 5: Computing recommended threshold = max(irr_p25, rel_p5)...")
        irr_p25 = irr_stats["p25"] if irr_stats["count"] > 0 else 0.0
        rel_p5 = rel_stats["p5"] if rel_stats["count"] > 0 else 0.0
        threshold_std = round(max(0.005, min(0.10, max(irr_p25, rel_p5))), 5)

        irr_p25_lr = irr_stats_lr["p25"] if irr_stats_lr["count"] > 0 else 0.0
        rel_p5_lr = rel_stats_lr["p5"] if rel_stats_lr["count"] > 0 else 0.0
        threshold_lr = round(max(0.005, min(0.10, max(irr_p25_lr, rel_p5_lr))), 5)

        std_sep = rel_stats["p50"] - irr_stats["p50"]
        lr_sep = rel_stats_lr["p50"] - irr_stats_lr["p50"]
        use_legacy_rank = bool(lr_sep > std_sep and irr_stats_lr["count"] > 0)
        final_threshold = threshold_lr if use_legacy_rank else threshold_std

        logger.info(
            "  threshold_std=%.5f  threshold_lr=%.5f  use_legacy_rank=%s",
            threshold_std, threshold_lr, use_legacy_rank,
        )

        logger.info("Step 6: Writing output JSON...")
        output: dict[str, Any] = {
            "run_uuid": run_uuid,
            "date": date_str,
            "scoring_algorithm_hint": scoring_hint,
            "recommended": {
                "threshold": final_threshold,
                "legacy_rank": use_legacy_rank,
                "CORTEX_RECALL_THRESHOLD": str(final_threshold),
                "CORTEX_RECALL_LEGACY_RANK": str(use_legacy_rank).lower(),
            },
            "stats": {
                "standard": {
                    "relevant": rel_stats,
                    "irrelevant": irr_stats,
                },
                "legacy_rank": {
                    "relevant": rel_stats_lr,
                    "irrelevant": irr_stats_lr,
                },
            },
            "calibration": {
                "memories_posted": len(memory_ids),
                "queries_run": len(golden_queries),
                "max_observed_score": round(max_score, 6),
            },
        }
        output_file = output_dir / f"threshold-recommendation-{date_str}.json"
        output_file.write_text(json.dumps(output, indent=2))
        logger.info("Output written to: %s", output_file)

        logger.info("Step 7: Cleaning up %d calibration memories...", len(memory_ids))
        failed_cleanup = 0
        for mem_id in memory_ids:
            if not forget_memory(client, args.url, args.api_key, mem_id):
                failed_cleanup += 1
        if failed_cleanup:
            logger.warning(
                "Cleanup: %d/%d memories NOT forgotten — manual cleanup may be needed",
                failed_cleanup,
                len(memory_ids),
            )
        else:
            logger.info("Cleanup complete: all %d memories forgotten", len(memory_ids))

    print(
        f"RECOMMENDED: CORTEX_RECALL_THRESHOLD={final_threshold} "
        f"CORTEX_RECALL_LEGACY_RANK={str(use_legacy_rank).lower()}"
    )


if __name__ == "__main__":
    main()
