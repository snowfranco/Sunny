"""Artist, v1 scaffold. The bar: a valid image file + a caption. Nothing
more. No quality rubric, no retry loop, no style system yet (explicitly
deferred by the brief).

The image is a locally generated SVG card derived from the post's angle
title: deterministic, dependency-free, always valid. When an image-gen API
gets chosen later, this module is the single place to swap it in; the
ArtistOutput schema and the orchestrator call site stay the same.
"""

from __future__ import annotations

import html

from . import db, llm
from . import schemas as S
from .config import load_config

_SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630" viewBox="0 0 1200 630">
  <rect width="1200" height="630" fill="#14161a"/>
  <rect x="40" y="40" width="1120" height="550" fill="none" stroke="#2c3038" stroke-width="2" rx="18"/>
  <text x="80" y="140" font-family="Georgia, serif" font-size="30" fill="#9a978f">{pillar}</text>
  <text x="80" y="260" font-family="Georgia, serif" font-size="54" fill="#e8e6e1">{line1}</text>
  <text x="80" y="330" font-family="Georgia, serif" font-size="54" fill="#e8e6e1">{line2}</text>
  <rect x="80" y="500" width="140" height="6" fill="#e8b04b"/>
  <text x="80" y="560" font-family="Georgia, serif" font-size="26" fill="#9a978f">snow abad · building in public</text>
</svg>
"""


def _wrap_title(title: str, width: int = 34) -> tuple[str, str]:
    words = title.split()
    line1, line2 = "", ""
    for w in words:
        if len(line1) + len(w) + 1 <= width:
            line1 = f"{line1} {w}".strip()
        elif len(line2) + len(w) + 1 <= width:
            line2 = f"{line2} {w}".strip()
        else:
            line2 = (line2 + "…") if line2 else "…"
            break
    return line1, line2


def generate(conn, post_id: str, client: llm.LLMClient | None = None) -> S.ArtistOutput:
    """Placeholder image + LLM caption for a post's latest draft."""
    draft = db.get_latest_draft(conn, post_id)
    if not draft:
        raise KeyError(f"no draft for post {post_id}")
    angle = db.get_angle(conn, draft.angle_id)
    title = angle.title if angle else "Working notes"

    cfg = load_config()
    cfg.images_path.mkdir(parents=True, exist_ok=True)
    image_path = cfg.images_path / f"{post_id}.svg"
    line1, line2 = _wrap_title(title)
    image_path.write_text(
        _SVG.format(pillar=html.escape(draft.pillar.replace("_", " ")),
                    line1=html.escape(line1), line2=html.escape(line2)),
        encoding="utf-8")

    client = client or llm.LLMClient(run_id=f"artist-{post_id[:8]}")
    caption = client.complete_text(
        "caption",
        "Write one image caption in Snow Abad's voice: specific, wry, no "
        "hashtags, no em dashes, under 140 characters.",
        f"POST TITLE: {title}\n\nDRAFT OPENING:\n{draft.draft_text[:400]}",
        max_tokens=100,
    ).strip()

    out = S.ArtistOutput(
        post_id=post_id,
        image_path=str(image_path),
        caption=caption,
        generated_at=S.now_iso(),
    )
    db.save_artist_output(conn, out)
    return out
