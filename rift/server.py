"""Local read API and viewer host.

GET  /api/cases                         case list (executed cases)
GET  /api/cases/<case_id>               CaseView
GET  /api/project                       project record (gates, formal, benchmark, screen, locks)
GET  /api/trace/<run_id>?op=&from=&to=  TraceSelection (bounded window)
GET  /api/artifacts/<run_id>/<file>     authorized artifact file from the immutable store
GET  /api/specimens                     illustrative fixtures (separate example/ namespace)
GET  /api/jobs                          replay jobs (only meaningful with --allow-run)
POST /api/replay                        enqueue a budgeted RTL replay of a case workload (requires --allow-run)

The server never writes evidence except through the controller's run store,
never serves experiments/heldout/, and rejects path traversal.
"""

from __future__ import annotations

import json
import mimetypes
import threading
import time
import traceback
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from rift.paths import ARTIFACTS, ROOT, RUNS, STUDIES
from rift.presentation import adapter

UI_DIST = ROOT / "ui" / "dist"
JOBS_LOG = ARTIFACTS / "jobs.jsonl"
MAX_REPLAY_BUDGET = 4


class Controller:
    """Budgeted replay jobs: queued -> running -> completed | failed."""

    def __init__(self):
        self.jobs: dict[str, dict] = {}
        self.lock = threading.Lock()

    def _log(self, job):
        JOBS_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(JOBS_LOG, "a") as f:
            f.write(json.dumps({k: v for k, v in job.items() if k != "thread"}) + "\n")

    def submit(self, case_id: str, budget: int) -> dict:
        if budget < 2 or budget > MAX_REPLAY_BUDGET:
            raise ValueError(f"replay budget must be between 2 and {MAX_REPLAY_BUDGET} RTL executions")
        view = adapter.case_view(case_id)
        job = {"job_id": uuid.uuid4().hex[:12], "case_id": case_id, "state": "QUEUED", "budget_rtl_executions": budget,
               "used_rtl_executions": 0, "submitted": time.time(), "presentation_mode": "LIVE_EXECUTION", "result": None, "error": None}
        with self.lock:
            self.jobs[job["job_id"]] = job
        self._log(job)
        threading.Thread(target=self._run, args=(job, view), daemon=True).start()
        return job

    def _run(self, job, view):
        from rift.contracts.config import load_config
        from rift.contracts.workload import validate_and_compile
        from rift.evaluate.compare import classify
        from rift.rtl import run_rtl
        try:
            job["state"] = "RUNNING"
            self._log(job)
            w = view["workload"]["workload"]
            checks, ids = {}, {}
            for d in view["designs"]:
                if job["used_rtl_executions"] + 1 > job["budget_rtl_executions"]:
                    raise RuntimeError("budget exhausted")
                cfg = load_config(d["config"])
                reference_id = view["comparison"]["rtl_run_ids"][d["design"]]
                recorded = json.loads((RUNS / reference_id / "manifest.json").read_text())
                r = run_rtl(cfg, validate_and_compile(w, cfg),
                            stalls=tuple(tuple(s) for s in recorded.get("stalls", [])),
                            inject=recorded.get("cpp_inject"), sv_inject=recorded.get("sv_inject_mask", 0),
                            timeout=recorded.get("timeout_cycles", 4096),
                            tags=("viewer_replay", view["case_id"]))
                job["used_rtl_executions"] += 1
                checks[d["design"]], ids[d["design"]] = r["check"], r["run_id"]
            rec = view["comparison"]
            model = {d: json.loads((RUNS / rec["model_run_ids"][d] / "check.json").read_text()) for d in rec["admitted_order"]}
            original = {d: json.loads((RUNS / rec["rtl_run_ids"][d] / "check.json").read_text()) for d in rec["admitted_order"]}
            v = classify(rec["admitted_order"], model, checks) if model else None
            job["result"] = {"rtl_run_ids": ids, "rtl_costs": {d: checks[d].get("makespan") for d in checks},
                             "rtl_status": {d: checks[d]["status"] for d in checks}, "verdict_against_recorded_model": v["verdict"] if v else None,
                             "matches_recorded_reference": all(checks[d].get(k) == original[d].get(k) for d in checks for k in ("status", "makespan", "violation_counts"))}
            job["state"] = "COMPLETED"
        except Exception as e:
            job["state"] = "FAILED"
            job["error"] = f"{type(e).__name__}: {e}"
        job["finished"] = time.time()
        self._log(job)


def make_handler(allow_run: bool, controller: Controller):
    class Handler(BaseHTTPRequestHandler):
        server_version = "RIFT/0.1"

        def log_message(self, fmt, *args):
            pass

        def _json(self, obj, code=200):
            body = json.dumps(obj, default=str).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _file(self, path: Path):
            data = path.read_bytes()
            if path.name == "index.html":
                data = data.replace(b'<meta name="rift-transport" content="static"', b'<meta name="rift-transport" content="live"', 1)
            ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            if path.suffix == ".jsonl":
                ctype = "application/x-ndjson"
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            u = urlparse(self.path)
            parts = [unquote(p) for p in u.path.split("/") if p]
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            try:
                if parts[:1] == ["api"]:
                    return self._api(parts[1:], q)
                rel_path = "/".join(parts) or "index.html"
                target = (UI_DIST / rel_path).resolve()
                if UI_DIST.resolve() not in target.parents and target != UI_DIST.resolve():
                    return self._json({"error": "forbidden"}, 403)
                if not target.exists() or target.is_dir():
                    target = UI_DIST / "index.html"
                if not target.exists():
                    return self._json({"error": "viewer not built; run `npm run build` in ui/"}, 503)
                return self._file(target)
            except KeyError as e:
                return self._json({"error": f"not found: {e}"}, 404)
            except FileNotFoundError as e:
                return self._json({"error": f"not found: {e}"}, 404)
            except Exception as e:
                return self._json({"error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()[-1500:]}, 500)

        def _api(self, parts, q):
            if parts == ["cases"]:
                return self._json({"cases": adapter.list_cases(), "run_controls_enabled": allow_run})
            if len(parts) == 2 and parts[0] == "cases":
                return self._json(adapter.case_view(parts[1]))
            if parts == ["project"]:
                return self._json(adapter.project_record())
            if len(parts) == 2 and parts[0] == "diag":
                v = adapter.diagnostic_view(parts[1])
                return self._json(v) if v else self._json({"error": "no diagnostic for this case"}, 404)
            if parts == ["specimens"]:
                return self._json(adapter.specimens())
            if parts == ["map"]:
                v = adapter.map_view()
                return self._json(v) if v else self._json({"error": "no decision map recorded"}, 404)
            if len(parts) == 2 and parts[0] == "trace":
                return self._json(adapter.trace_selection(parts[1], q.get("op"), int(q["from"]) if "from" in q else None,
                                                          int(q["to"]) if "to" in q else None))
            if len(parts) >= 3 and parts[0] == "artifacts":
                run_id, name = parts[1], "/".join(parts[2:])
                for base in (RUNS, STUDIES):
                    root = (base / run_id).resolve()
                    if root.exists():
                        target = (root / name).resolve()
                        if root not in target.parents or not target.is_file():
                            return self._json({"error": "forbidden"}, 403)
                        return self._file(target)
                return self._json({"error": "unknown artifact"}, 404)
            if parts == ["jobs"]:
                return self._json({"run_controls_enabled": allow_run, "jobs": list(controller.jobs.values())})
            return self._json({"error": "unknown endpoint"}, 404)

        def do_POST(self):
            u = urlparse(self.path)
            if u.path != "/api/replay":
                return self._json({"error": "unknown endpoint"}, 404)
            if not allow_run:
                return self._json({"error": "run controls are disabled; start the server with --allow-run"}, 403)
            try:
                n = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(n) or b"{}")
                job = controller.submit(body["case_id"], int(body.get("budget_rtl_executions", 2)))
                return self._json(job, 202)
            except (KeyError, ValueError) as e:
                return self._json({"error": str(e)}, 400)

    return Handler


def serve(host: str = "127.0.0.1", port: int = 8770, allow_run: bool = False) -> None:
    controller = Controller()
    httpd = ThreadingHTTPServer((host, port), make_handler(allow_run, controller))
    print(json.dumps({"status": "SERVING", "url": f"http://{host}:{port}/", "run_controls_enabled": allow_run}), flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
