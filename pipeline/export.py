"""Export: draft bundle only. This system NEVER publishes.

The hard constraint, enforced at four layers, deliberately redundant:
1. ExportBundle validates status == "draft" on construction (schemas.py).
2. The export_bundles table has CHECK (status = 'draft') (db.py).
3. assert_never_publishes() runs on every export as a code-level assertion.
4. There is no code path anywhere in this package that calls a publish API;
   this module writes local files and stops. Do not add such a path.

A bundle is a directory under exports/<post_id>/ containing everything Snow
needs to publish MANUALLY, elsewhere, on her own account, in her own time.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from . import db
from . import schemas as S
from .config import load_config

# Grep-able tripwire: if someone tries to flip this, the assertion and the
# schema and the SQL CHECK all still stand in their way.
PUBLISHING_SUPPORTED = False


def assert_never_publishes(bundle: S.ExportBundle) -> None:
    """Code-level assertion required by the brief. Fails loudly if any
    future change tries to smuggle a non-draft bundle through."""
    assert PUBLISHING_SUPPORTED is False, \
        "publishing must never be supported by this system"
    assert bundle.status == "draft", \
        f"export bundle must be a draft, got {bundle.status!r}"


def export_bundle(conn, post_id: str) -> tuple[S.ExportBundle, Path]:
    """Assemble the draft bundle for a post: approved text, LinkedIn
    extract, Notes hook, image + caption if the artist ran."""
    edited = db.get_edited_post(conn, post_id)
    if not edited:
        raise KeyError(f"post {post_id} is not approved yet")
    rep = db.get_repurposed(conn, post_id)
    if not rep:
        raise KeyError(f"post {post_id} has no repurposed formats yet")
    art = db.get_artist_output(conn, post_id)
    draft = db.get_latest_draft(conn, post_id)
    pillar = draft.pillar if draft else "build_in_public"

    bundle = S.ExportBundle(
        post_id=post_id,
        status="draft",  # the only value the schema and the db accept
        post_text=edited.final_text,
        linkedin_extract=rep.linkedin_extract,
        notes_hook=rep.notes_hook,
        image_path=art.image_path if art else None,
        caption=art.caption if art else None,
        pillar=pillar,
        exported_at=S.now_iso(),
    )
    assert_never_publishes(bundle)
    db.save_export_bundle(conn, bundle)

    out_dir = load_config().exports_path / post_id
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "post.md").write_text(bundle.post_text + "\n", encoding="utf-8")
    (out_dir / "linkedin.md").write_text(bundle.linkedin_extract + "\n",
                                         encoding="utf-8")
    (out_dir / "notes-hook.txt").write_text(bundle.notes_hook + "\n",
                                            encoding="utf-8")
    if bundle.image_path and Path(bundle.image_path).exists():
        shutil.copy2(bundle.image_path, out_dir / Path(bundle.image_path).name)
        (out_dir / "caption.txt").write_text((bundle.caption or "") + "\n",
                                             encoding="utf-8")
    (out_dir / "bundle.json").write_text(
        json.dumps(bundle.to_dict(), indent=2) + "\n", encoding="utf-8")
    return bundle, out_dir
