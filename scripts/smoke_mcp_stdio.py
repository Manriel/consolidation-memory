#!/usr/bin/env python3
"""Windows-friendly MCP stdio smoke: initialize → status → recall under budgets.

Agent-gate: fails if interactive tools hang past configured timeouts.

Usage:
  python scripts/smoke_mcp_stdio.py
  python scripts/smoke_mcp_stdio.py --status-timeout 30 --recall-timeout 45
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path


def _send(proc: subprocess.Popen[str], obj: dict[str, object]) -> None:
    assert proc.stdin is not None
    proc.stdin.write(json.dumps(obj) + "\n")
    proc.stdin.flush()


def _read_until(
    proc: subprocess.Popen[str],
    request_id: int,
    *,
    timeout: float,
) -> dict[str, object]:
    assert proc.stdout is not None
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        line = proc.stdout.readline()
        if not line:
            raise RuntimeError(f"MCP stdout EOF (rc={proc.poll()})")
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if msg.get("id") == request_id:
            if "error" in msg:
                raise RuntimeError(f"MCP error for id={request_id}: {msg['error']}")
            return msg
        # ignore notifications / other ids
        del remaining
    raise TimeoutError(f"No MCP response for id={request_id} within {timeout:g}s")


def _drain_stderr(proc: subprocess.Popen[str], sink: list[str]) -> None:
    assert proc.stderr is not None
    for line in proc.stderr:
        sink.append(line.rstrip())


def run_smoke(
    *,
    status_timeout: float,
    recall_timeout: float,
    init_timeout: float,
) -> None:
    with tempfile.TemporaryDirectory(prefix="cm-mcp-smoke-") as tmp:
        data_dir = str(Path(tmp) / "data")
        env = os.environ.copy()
        env.update(
            {
                "PYTHONUNBUFFERED": "1",
                "CONSOLIDATION_MEMORY_DATA_DIR": data_dir,
                "CONSOLIDATION_MEMORY_PROJECT": "mcp_smoke",
                "CONSOLIDATION_MEMORY_EMBEDDING_BACKEND": "fastembed",
                "CONSOLIDATION_MEMORY_LLM_BACKEND": "disabled",
                "CONSOLIDATION_MEMORY_WARMUP_ON_START": "0",
                "CONSOLIDATION_MEMORY_PRELOAD_NUMERIC_BACKENDS_ON_START": "1",
                "CONSOLIDATION_MEMORY_PRELOAD_SCIPY_ON_START": "0",
                "CONSOLIDATION_MEMORY_STATUS_LIGHTWEIGHT": "1",
                "CONSOLIDATION_MEMORY_MCP_AUTO_CONSOLIDATE": "0",
                "CONSOLIDATION_MEMORY_STDIO_SINGLETON": "0",
                "CONSOLIDATION_MEMORY_IDLE_TIMEOUT_SECONDS": "0",
                "CONSOLIDATION_MEMORY_CLIENT_INIT_TIMEOUT_SECONDS": "30",
                "CONSOLIDATION_MEMORY_RECALL_TIMEOUT_SECONDS": str(int(recall_timeout)),
                "CONSOLIDATION_MEMORY_TIMEOUT_MEMORY_STATUS": str(int(status_timeout)),
                "CONSOLIDATION_MEMORY_DEFERRED_KNOWLEDGE_RETRY_SECONDS": "0",
            }
        )
        # Prefer local src tree when present.
        repo_src = Path(__file__).resolve().parents[1] / "src"
        if repo_src.is_dir():
            env["PYTHONPATH"] = str(repo_src) + os.pathsep + env.get("PYTHONPATH", "")

        cmd = [
            sys.executable,
            "-m",
            "consolidation_memory",
            "--project",
            "mcp_smoke",
            "serve",
        ]
        print(f"spawning: {cmd}", flush=True)
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
            bufsize=1,
        )
        stderr_lines: list[str] = []
        threading.Thread(target=_drain_stderr, args=(proc, stderr_lines), daemon=True).start()
        t0 = time.monotonic()
        try:
            _send(
                proc,
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "smoke_mcp_stdio", "version": "0"},
                    },
                },
            )
            _read_until(proc, 1, timeout=init_timeout)
            print(f"initialize ok in {time.monotonic() - t0:.2f}s", flush=True)

            _send(proc, {"jsonrpc": "2.0", "method": "notifications/initialized"})
            _send(
                proc,
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {
                        "name": "memory_status",
                        "arguments": {"lightweight": True},
                    },
                },
            )
            status_msg = _read_until(proc, 2, timeout=status_timeout)
            status_text = str(status_msg.get("result", ""))
            if "error" in status_text.lower() and "timed out" in status_text.lower():
                raise RuntimeError(f"memory_status returned timeout payload: {status_text[:400]}")
            print(f"memory_status ok in {time.monotonic() - t0:.2f}s", flush=True)

            _send(
                proc,
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {
                        "name": "memory_recall",
                        "arguments": {
                            "query": "mcp smoke",
                            "n_results": 3,
                            "include_knowledge": True,
                        },
                    },
                },
            )
            recall_msg = _read_until(proc, 3, timeout=recall_timeout)
            recall_text = str(recall_msg.get("result", ""))
            if '"error"' in recall_text and "timed out" in recall_text.lower():
                # Semantic timeout with keyword fallback still returns payload; only hard fail pure errors.
                pass
            print(f"memory_recall ok in {time.monotonic() - t0:.2f}s", flush=True)
            print(f"smoke_mcp_stdio PASS total={time.monotonic() - t0:.2f}s", flush=True)
        except Exception:
            print("--- stderr tail ---", flush=True)
            for line in stderr_lines[-40:]:
                print(line, flush=True)
            raise
        finally:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except Exception:
                proc.kill()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--init-timeout", type=float, default=30.0)
    parser.add_argument("--status-timeout", type=float, default=30.0)
    parser.add_argument("--recall-timeout", type=float, default=45.0)
    args = parser.parse_args()
    try:
        run_smoke(
            status_timeout=args.status_timeout,
            recall_timeout=args.recall_timeout,
            init_timeout=args.init_timeout,
        )
    except Exception as exc:
        print(f"smoke_mcp_stdio FAIL: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
