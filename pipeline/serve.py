"""On-demand local server for the single-page interface (web/index.html).

Started explicitly with `python3 -m pipeline serve`, killed with Ctrl-C.
This is not an always-on server; it exists while Snow is using the page.
The daily cron never needs it (cron writes data/suggestions.json, which
this server merely reads back).

stdlib http.server only, JSON endpoints, one page, no framework.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

from . import angle_engine, config, db, refinement
from . import schemas as S
from .config import REPO_ROOT, load_config

WEB_DIR = REPO_ROOT / "web"


def _json_bytes(obj) -> bytes:
    return json.dumps(obj, indent=2).encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    server_version = "sunny/0.1"

    # -- plumbing -----------------------------------------------------------

    def _send(self, code: int, body: bytes, ctype: str = "application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _ok(self, obj):
        self._send(200, _json_bytes(obj))

    def _err(self, code: int, msg: str):
        self._send(code, _json_bytes({"error": msg}))

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def log_message(self, fmt, *args):  # quieter default logging
        pass

    # -- routes ---------------------------------------------------------------

    def do_GET(self):
        url = urlparse(self.path)
        conn = self.server.db_conn  # type: ignore[attr-defined]
        if url.path in ("/", "/index.html"):
            page = (WEB_DIR / "index.html").read_bytes()
            self._send(200, page, "text/html; charset=utf-8")
        elif url.path == "/api/suggestions":
            f = self.server.cfg.suggestions_file  # type: ignore[attr-defined]
            if f.exists():
                data = json.loads(f.read_text(encoding="utf-8"))
            else:
                data = {"generated_at": None, "project_suggestions": [],
                        "landscape_suggestions": []}
            # Surface mock mode so the page can say so out loud; a server
            # started without PIPELINE_MODEL in its shell serves canned
            # angle/draft output and this is the tell.
            data["mock_mode"] = config.mock_mode()
            self._ok(data)
        elif url.path == "/api/notes":
            self._ok([n.to_dict() for n in db.list_notes(conn)])
        elif url.path == "/api/angles":
            q = parse_qs(url.query)
            note_id = (q.get("note_id") or [""])[0]
            self._ok([a.to_dict() for a in db.list_angles_for_note(conn, note_id)])
        else:
            self._err(404, f"no route {url.path}")

    def do_POST(self):
        url = urlparse(self.path)
        conn = self.server.db_conn  # type: ignore[attr-defined]
        try:
            body = self._body()
            if url.path == "/api/capture":
                note = self._capture(conn, body)
                self._ok(note.to_dict())
            elif url.path == "/api/generate_angles":
                self._ok(self._generate_angles(conn, body))
            elif url.path == "/api/refine_angle":
                self._ok(self._refine_angle(conn, body))
            elif url.path == "/api/pick_angle":
                self._ok(self._pick(conn, body))
            elif url.path == "/api/run":
                self._ok(self._run(conn, body))
            elif url.path == "/api/edit_refine":
                self._ok(self._edit_refine(conn, body))
            elif url.path == "/api/approve_post":
                self._ok(self._approve(conn, body))
            elif url.path == "/api/export":
                self._ok(self._export(conn, body))
            else:
                self._err(404, f"no route {url.path}")
        except refinement.RefinementCapReached:
            self._ok({"cap_reached": True,
                      "prompt": refinement.FORCE_DECISION_PROMPT})
        except (S.SchemaError, KeyError, json.JSONDecodeError) as e:
            self._err(400, str(e))
        except Exception as e:  # surface, don't die
            self._err(500, f"{type(e).__name__}: {e}")

    # -- handlers -------------------------------------------------------------

    def _capture(self, conn, body: dict) -> S.CaptureNote:
        from .capture import capture_manual
        return capture_manual(conn, str(body["raw_text"]))

    def _generate_angles(self, conn, body: dict) -> dict:
        note = db.get_note(conn, str(body["note_id"]))
        if not note:
            raise KeyError(f"no note {body['note_id']}")
        angles = angle_engine.generate_angles(conn, note)
        session = refinement.start_session(conn, "angle")
        session.engine_turn(
            "Here are 3 angle options. Reply to refine, or pick one.",
            resulting_id=None)
        return {"session_id": session.session_id,
                "angles": [a.to_dict() for a in angles],
                "turns_remaining": session.turns_remaining}

    def _refine_angle(self, conn, body: dict) -> dict:
        session = refinement.RefinementSession(
            conn, str(body["session_id"]), "angle")
        base = db.get_angle(conn, str(body["angle_id"]))
        if not base:
            raise KeyError(f"no angle {body['angle_id']}")
        message = str(body["message"])
        session.user_turn(message)  # raises RefinementCapReached at the cap
        revised = angle_engine.refine_angle(conn, base, message)
        session.engine_turn(f"Revised: {revised.title}", resulting_id=revised.angle_id)
        out = {"angle": revised.to_dict(),
               "turns_remaining": session.turns_remaining}
        if session.cap_reached:
            out["prompt"] = refinement.FORCE_DECISION_PROMPT
        return out

    def _pick(self, conn, body: dict) -> dict:
        angle = db.get_angle(conn, str(body["angle_id"]))
        if not angle:
            raise KeyError(f"no angle {body['angle_id']}")
        picked = angle_engine.pick_angle(conn, angle)
        return {"picked": picked.to_dict(),
                "next": f"python3 -m pipeline run {angle.angle_id}"}

    def _run(self, conn, body: dict) -> dict:
        # Angle -> writer/reviewer loop -> draft awaiting edit. Mirrors
        # `pipeline run`; run_pipeline never publishes. The UI goes straight
        # from selection to here, so this click IS the pick: record it.
        from . import orchestrator
        angle_id = str(body["angle_id"])
        angle = db.get_angle(conn, angle_id)
        if not angle:
            raise KeyError(f"no angle {angle_id}")
        angle_engine.pick_angle(conn, angle)
        return orchestrator.run_pipeline(conn, angle_id)

    def _export(self, conn, body: dict) -> dict:
        # Mirrors `pipeline export`: repurpose if needed, then assemble the
        # draft bundle. There is no publish path; export writes local files.
        from . import export as export_mod
        from . import llm, repurpose
        from .runlog import log_step
        post_id = str(body["post_id"])
        run_id = S.new_id()
        if not db.get_repurposed(conn, post_id):
            repurpose.repurpose(conn, post_id, llm.LLMClient(run_id=run_id))
            log_step(conn, run_id, "repurpose", post_id,
                     output_ref="linkedin_extract+notes_hook")
        bundle, out_dir = export_mod.export_bundle(conn, post_id)
        log_step(conn, run_id, "export", post_id, output_ref=str(out_dir),
                 pass_fail=True)
        return {"bundle": bundle.to_dict(), "out_dir": str(out_dir)}

    def _edit_refine(self, conn, body: dict) -> dict:
        # Wired in Phase 2 (edit-stage refinement reuses the same session
        # pattern). Kept as a named route so the page is stable.
        from . import orchestrator
        return orchestrator.edit_refine_api(conn, body)

    def _approve(self, conn, body: dict) -> dict:
        from . import orchestrator
        return orchestrator.approve_api(conn, body)


def serve(port: int | None = None) -> None:
    cfg = load_config()
    conn = db.connect(cfg.db_path)
    db.init_db(conn)
    httpd = HTTPServer(("127.0.0.1", port or cfg.serve_port), Handler)
    httpd.cfg = cfg          # type: ignore[attr-defined]
    httpd.db_conn = conn     # type: ignore[attr-defined]
    print(f"sunny local page: http://127.0.0.1:{httpd.server_port}/  (Ctrl-C stops)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        conn.close()
