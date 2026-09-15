"""Fixed corpus used for benchmarks. Seeded once; never rewritten per run."""

BENCHMARK_QUERY = "Recall workspace semantic retrieval latency"

BENCHMARK_DOCS = [
    {
        "id": "bench::shared-0",
        "text": "Recall workspace semantic retrieval latency benchmark document about planner executor reviewer orchestration.",
        "metadata": {"workspace_id": "bench-shared", "kind": "benchmark"},
    },
    {
        "id": "bench::shared-1",
        "text": "Moss Cloud hybrid search compared with a local Qdrant vector fallback for cold storage queries.",
        "metadata": {"workspace_id": "bench-shared", "kind": "benchmark"},
    },
    {
        "id": "bench::shared-2",
        "text": "Postgres remains the source of truth for tasks, messages, and audit logs in the Recall workspace.",
        "metadata": {"workspace_id": "bench-shared", "kind": "benchmark"},
    },
]
