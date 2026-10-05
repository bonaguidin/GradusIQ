"""Guards the production routing contract between FastAPI and the frontend.

Vercel never forwards a browser request to the backend directly: every
``/api/v2/student/me/*`` path must have a matching entry in BOTH
``frontend/vercel.json``'s ``rewrites`` (which path Vercel's edge will
rewrite to the proxy function) AND ``frontend/api/proxy.mjs``'s ``ME_TARGETS``
closed allowlist (which targets the proxy function itself will forward). A
route can exist in FastAPI's real route table and still be completely
unreachable in production if either piece is missing -- the local Vite dev
proxy forwards every ``/api/*`` path unconditionally, so this gap is
invisible in local dev, in pytest, and in the frontend's own Playwright
suite, which is exactly how two routes (``/job-search``, then found to
already apply to ``/career-role-options``) shipped broken in production
with every other suite green. See planning-docs/outstanding-fixes.md and the
fix/api-proxy-allowlist-gaps branch.

This test is the only thing that will catch the next one.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from GradusIQ_career.api import APIConfig, create_app

REPO_ROOT = Path(__file__).resolve().parent.parent
VERCEL_JSON_PATH = REPO_ROOT / "frontend" / "vercel.json"
PROXY_MJS_PATH = REPO_ROOT / "frontend" / "api" / "proxy.mjs"

ME_ROUTE_PREFIX = "/api/v2/student/me"

_PARAM = re.compile(r":([A-Za-z_]+)|\{([A-Za-z_]+)\}")


def _normalize(path: str) -> str:
    """A path-shape fingerprint that ignores path-param names.

    Vercel's `:student` and FastAPI's `{student_slug}` describe the same
    shape with different spellings -- this collapses both (and every other
    param name) to one placeholder so the two sides compare on shape alone.
    """
    return _PARAM.sub("{*}", path)


def _real_me_routes() -> dict[str, tuple[str, frozenset[str]]]:
    """normalized path -> (original path, HTTP methods), straight from the
    live FastAPI app -- not a hand-maintained list that can itself drift."""
    app = create_app(
        APIConfig(
            proxy_secret="test-proxy-secret",
            allowed_origins=(),
            rate_limit_requests=100,
            rate_limit_window_seconds=60.0,
            max_concurrent_ai_requests=2,
        )
    )
    # FastAPI 's app.routes wraps the included APIRouter lazily; the actual
    # Route objects (with .path/.methods) live on original_router.routes.
    included = app.routes[0]
    router = included.original_router
    routes: dict[str, tuple[str, frozenset[str]]] = {}
    for route in router.routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None)
        if not path or not path.startswith(ME_ROUTE_PREFIX):
            continue
        routes[_normalize(path)] = (path, frozenset((methods or set()) - {"HEAD"}))
    assert routes, "Found zero /me routes -- the route-table introspection broke, not the app."
    return routes


def _vercel_me_rewrites() -> dict[str, tuple[str, str | None]]:
    """normalized source path -> (original source, target query param)."""
    data = json.loads(VERCEL_JSON_PATH.read_text())
    rewrites: dict[str, tuple[str, str | None]] = {}
    for rewrite in data["rewrites"]:
        source = rewrite["source"]
        if source == "/(.*)":  # the SPA catch-all, not an API route
            continue
        if not source.startswith(ME_ROUTE_PREFIX):
            continue
        target_match = re.search(r"target=([a-z0-9-]+)", rewrite["destination"])
        rewrites[_normalize(source)] = (source, target_match.group(1) if target_match else None)
    assert rewrites, "Found zero /me rewrites -- the vercel.json parsing broke, not the config."
    return rewrites


def _proxy_me_targets() -> set[str]:
    """The exact set of keys ME_TARGETS allowlists in proxy.mjs."""
    src = PROXY_MJS_PATH.read_text()
    match = re.search(
        r"const ME_TARGETS = Object\.assign\(Object\.create\(null\), \{(.*?)\n\}\)",
        src,
        re.DOTALL,
    )
    assert match, "Could not find ME_TARGETS in proxy.mjs -- did its shape change?"
    keys = set(re.findall(r"'([a-z0-9-]+)':\s*\{", match.group(1)))
    assert keys, "Found zero ME_TARGETS keys -- the proxy.mjs parsing broke, not the file."
    return keys


def test_every_fastapi_me_route_has_a_vercel_rewrite():
    real = _real_me_routes()
    rewrites = _vercel_me_rewrites()
    missing = sorted(set(real) - set(rewrites))
    assert not missing, (
        "These FastAPI /api/v2/student/me/* routes have NO matching vercel.json "
        "rewrite, so a real Vercel deployment can never forward a browser "
        "request to them -- the frontend's fetch() would 404 or hit the SPA "
        "catch-all, even though every local/pytest/dev-proxy path works fine. "
        "Add a rewrite (and a matching ME_TARGETS entry in proxy.mjs) for each: "
        + ", ".join(real[path][0] for path in missing)
    )


def test_every_vercel_me_rewrite_still_points_at_a_real_route():
    real = _real_me_routes()
    rewrites = _vercel_me_rewrites()
    stale = sorted(set(rewrites) - set(real))
    assert not stale, (
        "These vercel.json /api/v2/student/me/* rewrites no longer match any "
        "real FastAPI route -- the backend route behind them was probably "
        "renamed or removed. Dead routing surface, not a live break, but "
        "worth cleaning up: " + ", ".join(rewrites[path][0] for path in stale)
    )


def test_every_vercel_me_rewrite_target_is_in_proxy_mjs_allowlist():
    rewrites = _vercel_me_rewrites()
    targets = _proxy_me_targets()
    missing = sorted(
        source for source, target in rewrites.values() if target and target not in targets
    )
    assert not missing, (
        "These vercel.json rewrites reference a `target=` that proxy.mjs's "
        "ME_TARGETS allowlist doesn't have, so the proxy function itself would "
        "reject the request with its own 400 even though the URL rewrote "
        "correctly: " + ", ".join(missing)
    )


def test_every_proxy_mjs_me_target_is_referenced_by_a_vercel_rewrite():
    rewrites = _vercel_me_rewrites()
    targets = _proxy_me_targets()
    referenced = {target for _source, target in rewrites.values() if target}
    orphaned = sorted(targets - referenced)
    assert not orphaned, (
        "These proxy.mjs ME_TARGETS entries are never reachable from any "
        "vercel.json rewrite -- dead allowlist entries, not a live break, but "
        "worth cleaning up (or they were meant to be wired and the rewrite was "
        "forgotten): " + ", ".join(orphaned)
    )
