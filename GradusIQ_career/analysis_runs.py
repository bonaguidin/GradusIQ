"""Background GAP/FIT/SHIFT runs.

A live run often takes four to seven minutes (reasoning model, repair
attempts, role research), longer than the frontend proxy's 300-second limit.
So the browser starts a run with one short request and then asks for its
status every few seconds; the run itself happens on a thread here.

State lives in this process only. That is enough because the backend runs as
a single worker (api._assert_single_worker_deployment) and a finished result
is also saved to the analysis cache. If the server restarts mid-run, the run
is lost and a status read answers "none", which the page reports as a run
that stopped before finishing.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

# Finished runs stay readable this long, so a page that polls a little late
# (a laptop waking up, a slow network) still gets its result.
KEEP_FINISHED_SECONDS = 15 * 60


@dataclass
class AnalysisRun:
    feature: str
    started_at: float
    state: str = "running"  # running | done | failed
    finished_at: float | None = None
    result: Any = None
    status_code: int | None = None
    detail: str | None = None
    thread: threading.Thread | None = field(default=None, repr=False)

    def to_client(self, now: float) -> dict:
        end = self.finished_at if self.finished_at is not None else now
        body: dict[str, Any] = {"state": self.state, "elapsed_seconds": round(end - self.started_at, 1)}
        if self.state == "done":
            body["result"] = self.result
        elif self.state == "failed":
            body["status_code"] = self.status_code
            body["detail"] = self.detail
        return body


class AnalysisRunRegistry:
    """At most one run per (student, feature); thread-safe."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._runs: dict[tuple[str, str], AnalysisRun] = {}

    def get(self, student_id: str, feature: str) -> AnalysisRun | None:
        with self._lock:
            self._prune()
            return self._runs.get((student_id, feature))

    def running(self, student_id: str, feature: str) -> AnalysisRun | None:
        run = self.get(student_id, feature)
        return run if run is not None and run.state == "running" else None

    def start(
        self,
        student_id: str,
        feature: str,
        work: Callable[[], Any],
        on_error: Callable[[BaseException], tuple[int, str]],
    ) -> tuple[AnalysisRun, bool]:
        """Start `work` on a thread unless this run is already going.

        Returns (run, started). `on_error` maps an exception from `work` to the
        (status_code, detail) the page shows.
        """
        key = (student_id, feature)
        with self._lock:
            self._prune()
            current = self._runs.get(key)
            if current is not None and current.state == "running":
                return current, False
            run = AnalysisRun(feature=feature, started_at=self._clock())
            self._runs[key] = run

        def target() -> None:
            try:
                result = work()
            except BaseException as exc:  # noqa: BLE001 -- reported to the page, never re-raised
                status_code, detail = on_error(exc)
                with self._lock:
                    run.state, run.status_code, run.detail = "failed", status_code, detail
                    run.finished_at = self._clock()
                return
            with self._lock:
                run.state, run.result = "done", result
                run.finished_at = self._clock()

        run.thread = threading.Thread(target=target, name=f"analysis-{feature}", daemon=True)
        run.thread.start()
        return run, True

    def _prune(self) -> None:
        cutoff = self._clock() - KEEP_FINISHED_SECONDS
        for key, run in list(self._runs.items()):
            if run.finished_at is not None and run.finished_at < cutoff:
                del self._runs[key]
