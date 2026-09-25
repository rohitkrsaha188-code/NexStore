"""Rebalancer: move replicas from over-utilized to under-utilized nodes.

Source replicas are only deleted after the destination copy verifies — that
guarantee lives inside ReplicaManager.migrate_replica.
"""
from __future__ import annotations

import logging

from backend.database import db, log_activity, utcnow
from backend.replication.replica_manager import ReplicaManager
from backend.rebalancing.migration import run_migration

logger = logging.getLogger("vault.rebalancer")


def plan_rebalance(threshold: int, max_moves: int = 5) -> list[dict]:
    """Choose replica moves that reduce the highest utilizations."""
    nodes = db.query_all("SELECT node_id, capacity, used_capacity FROM nodes ORDER BY node_id")
    if not nodes:
        return []
    total_capacity = sum(n["capacity"] for n in nodes)
    avg_util = 100 * sum(n["used_capacity"] for n in nodes) / total_capacity if total_capacity else 0

    overloaded = [
        n for n in nodes
        if n["capacity"] and (100 * n["used_capacity"] / n["capacity"]) > threshold
    ]
    underloaded = [
        n for n in nodes
        if n["capacity"] and (100 * n["used_capacity"] / n["capacity"]) < avg_util
        and n["node_id"] not in {o["node_id"] for o in overloaded}
    ]
    if not overloaded or not underloaded:
        return []

    moves: list[dict] = []
    for source in overloaded:
        candidates = db.query_all(
            """
            SELECT r.replica_id, r.object_id, r.size, r.node_id
            FROM replicas r
            JOIN objects o ON o.object_id = r.object_id
            WHERE r.node_id=? AND r.status='HEALTHY'
              AND (SELECT COUNT(*) FROM replicas r2 WHERE r2.object_id=r.object_id) > 1
            ORDER BY r.size DESC
            """,
            (source["node_id"],),
        )
        for candidate in candidates:
            if len(moves) >= max_moves:
                return moves
            dest = next(
                (u for u in underloaded
                 if u["node_id"] not in {
                     m["dest_node_id"] for m in moves
                 } and u["node_id"] not in {
                     x["node_id"] for x in db.query_all(
                         "SELECT node_id FROM replicas WHERE object_id=? AND replica_id != ?",
                         (candidate["object_id"], candidate["replica_id"]),
                     )
                 }),
                None,
            )
            if dest is None:
                continue
            moves.append({
                "replica_id": candidate["replica_id"],
                "object_id": candidate["object_id"],
                "source_node_id": source["node_id"],
                "dest_node_id": dest["node_id"],
                "size": candidate["size"],
            })
    return moves


def execute_rebalance(replicas: ReplicaManager, threshold: int, max_moves: int = 5) -> dict:
    """Plan and run rebalance moves, recording each as a rebalance_jobs row."""
    moves = plan_rebalance(threshold, max_moves)
    if not moves:
        return {"planned": 0, "completed": 0, "failed": 0, "moves": [], "message": "No rebalancing needed"}

    with db.write() as conn:
        log_activity(conn, "REBALANCE_STARTED",
                     f"Rebalance started: {len(moves)} planned move(s)")

    completed, failed, move_rows = 0, 0, []
    for move in moves:
        job_id = f"rb_{move['replica_id']}_{utcnow()[-8:].replace(':', '')}"
        with db.write() as conn:
            conn.execute(
                "INSERT INTO rebalance_jobs(job_id, replica_id, object_id, source_node_id, "
                "dest_node_id, status, progress, created_at) VALUES(?,?,?,?,?, 'QUEUED', 0, ?)",
                (job_id, move["replica_id"], move["object_id"], move["source_node_id"],
                 move["dest_node_id"], utcnow()),
            )
        result = run_migration(
            replicas, replica_id=move["replica_id"], dest_node_id=move["dest_node_id"], job_id=job_id
        )
        if result["status"] == "COMPLETED":
            completed += 1
        else:
            failed += 1
        move_rows.append({**move, "job_id": job_id, "status": result["status"]})

    return {"planned": len(moves), "completed": completed, "failed": failed, "moves": move_rows}


def rebalance_status() -> dict:
    jobs = db.query_all(
        "SELECT * FROM rebalance_jobs ORDER BY created_at DESC LIMIT 50"
    )
    return {
        "active": len([j for j in jobs if j["status"] in ("QUEUED", "RUNNING")]),
        "completed": len([j for j in jobs if j["status"] == "COMPLETED"]),
        "failed": len([j for j in jobs if j["status"] == "FAILED"]),
        "bytes_moved": sum(j["bytes_moved"] for j in jobs if j["status"] == "COMPLETED"),
        "jobs": jobs,
    }
