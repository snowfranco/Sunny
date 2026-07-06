"""Analytics: manual-trigger, paste-in first.

Blind spot flagged, not worked around: as of this build neither platform
offers a usable public stats API for this use case. Substack has no
official public API for post analytics. LinkedIn's post-analytics APIs sit
behind partner program access that individual accounts don't get. So the
paste-in path below IS the v1 mechanism, not a temporary fallback. If either
platform ships a real API later, add a fetcher here; the AnalyticsSnapshot
schema and everything downstream already fit.

Manual flow: Snow reads the numbers off the platform dashboards every week
or two and records them with one CLI line per post per platform.
"""

from __future__ import annotations

from . import db
from . import schemas as S

API_STATUS_NOTE = (
    "No usable public analytics API: Substack has no official stats API and "
    "LinkedIn post analytics require partner access. Manual paste-in is the "
    "v1 path by design."
)


def add_snapshot(conn, post_id: str, platform: str, views: int, likes: int,
                 comments: int, shares: int,
                 days_since_publish: int) -> S.AnalyticsSnapshot:
    snap = S.AnalyticsSnapshot(
        post_id=post_id,
        platform=platform,
        views=views,
        likes=likes,
        comments=comments,
        shares=shares,
        collected_at=S.now_iso(),
        days_since_publish=days_since_publish,
    )
    db.save_analytics(conn, snap)
    return snap


def snapshots_between(conn, start: str, end: str) -> list[S.AnalyticsSnapshot]:
    rows = conn.execute(
        "SELECT post_id, platform, views, likes, comments, shares, "
        "collected_at, days_since_publish FROM analytics_snapshots "
        "WHERE date(collected_at) BETWEEN ? AND ? ORDER BY collected_at",
        (start, end)).fetchall()
    return [S.AnalyticsSnapshot.from_dict(dict(r)) for r in rows]


def engagement_score(s: S.AnalyticsSnapshot) -> float:
    """Weighted engagement; comments and shares signal more than a view.
    Deliberately simple. Revisit at a 2-4 week review, not before."""
    return s.views * 0.01 + s.likes + s.comments * 3 + s.shares * 5
