"""
Minimal Flask app to manage thesis environments and run screenings.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from flask import Flask, jsonify, request, send_from_directory

from ..data.fetcher import DataFetcher
from ..screener.criteria import load_criteria_from_config, parse_inline_criteria
from ..screener.screener import StockScreener

APP_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = APP_ROOT / "data"
OUTPUTS_DIR = APP_ROOT / "outputs"
REPORTS_DIR = OUTPUTS_DIR / "reports"
ENVIRONMENTS_PATH = DATA_DIR / "environments.json"

DATA_DIR.mkdir(parents=True, exist_ok=True)
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

app = Flask(__name__, static_folder="static")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_environments() -> List[Dict[str, Any]]:
    if not ENVIRONMENTS_PATH.exists():
        return []
    try:
        return json.loads(ENVIRONMENTS_PATH.read_text())
    except Exception:
        return []


def _save_environments(environments: List[Dict[str, Any]]) -> None:
    ENVIRONMENTS_PATH.write_text(json.dumps(environments, indent=2))


def _find_environment(environments: List[Dict[str, Any]], env_id: str) -> Dict[str, Any] | None:
    for env in environments:
        if env.get("id") == env_id:
            return env
    return None


def _normalize_tickers(raw: str) -> List[str]:
    if not raw:
        return []
    return [t.strip().upper() for t in raw.replace("\n", ",").split(",") if t.strip()]


def _generate_analysis(results_df) -> str:
    if results_df.empty:
        return "No results were returned. Check tickers and data availability."

    passed = results_df[results_df["status"] == "PASS"]
    failed = results_df[results_df["status"] == "FAIL"]
    avg_pe = results_df["pe_ratio"].dropna().mean()
    avg_roe = results_df["roe"].dropna().mean()
    avg_growth = results_df["revenue_growth"].dropna().mean()

    lines = [
        f"Pass rate: {len(passed)}/{len(results_df)} tickers met all criteria.",
    ]
    if avg_pe is not None:
        lines.append(f"Average P/E: {avg_pe:.2f}.")
    if avg_roe is not None:
        lines.append(f"Average ROE: {avg_roe:.2%}.")
    if avg_growth is not None:
        lines.append(f"Average revenue growth: {avg_growth:.2%}.")

    if not failed.empty:
        common_failures = (
            failed["failed_criteria"]
            .dropna()
            .str.split(", ")
            .explode()
            .value_counts()
            .head(3)
            .index
            .tolist()
        )
        if common_failures:
            lines.append("Most common misses: " + "; ".join(common_failures) + ".")

    return " ".join(lines)


def _write_report(env: Dict[str, Any], results_df, analysis_text: str) -> Dict[str, str]:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    base_name = f"{env['id']}_{timestamp}"
    csv_path = REPORTS_DIR / f"{base_name}.csv"
    json_path = REPORTS_DIR / f"{base_name}.json"
    html_path = REPORTS_DIR / f"{base_name}.html"

    results_df.to_csv(csv_path, index=False)
    json_path.write_text(results_df.to_json(orient="records", indent=2))

    rows_html = "\n".join(
        [
            "<tr>" + "".join([f"<td>{value}</td>" for value in row]) + "</tr>"
            for row in results_df.fillna("").values.tolist()
        ]
    )
    header_html = "".join([f"<th>{col}</th>" for col in results_df.columns])

    html_path.write_text(
        f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{env['name']} Report</title>
  <style>
    body {{
      font-family: "IBM Plex Sans", "Space Grotesk", "Segoe UI", sans-serif;
      margin: 32px;
      color: #111;
      background: #f7f4ee;
    }}
    h1 {{ margin-bottom: 6px; }}
    .meta {{ color: #555; margin-bottom: 16px; }}
    .analysis {{
      padding: 16px;
      background: #fff5d7;
      border-radius: 12px;
      margin-bottom: 24px;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      background: white;
    }}
    th, td {{
      padding: 10px 12px;
      border-bottom: 1px solid #eee;
      text-align: left;
      font-size: 14px;
    }}
    th {{
      background: #111;
      color: #fff;
      position: sticky;
      top: 0;
    }}
  </style>
</head>
<body>
  <h1>{env['name']} Thesis Report</h1>
  <div class="meta">Generated {datetime.now(timezone.utc).isoformat()}</div>
  <div class="analysis">{analysis_text}</div>
  <table>
    <thead><tr>{header_html}</tr></thead>
    <tbody>{rows_html}</tbody>
  </table>
</body>
</html>"""
    )

    return {
        "csv": str(csv_path),
        "json": str(json_path),
        "html": str(html_path),
    }


@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/<path:path>")
def static_files(path: str):
    return send_from_directory(app.static_folder, path)


@app.route("/api/environments", methods=["GET"])
def list_environments():
    return jsonify(_load_environments())


@app.route("/api/environments", methods=["POST"])
def create_environment():
    payload = request.get_json(force=True) or {}
    envs = _load_environments()

    env_id = str(uuid.uuid4())
    env = {
        "id": env_id,
        "name": payload.get("name", "Untitled Thesis").strip() or "Untitled Thesis",
        "thesis": payload.get("thesis", "").strip(),
        "tickers": _normalize_tickers(payload.get("tickers", "")),
        "criteria": parse_inline_criteria(payload.get("criteria", "")),
        "created_at": _utc_now(),
        "updated_at": _utc_now(),
    }
    envs.append(env)
    _save_environments(envs)
    return jsonify(env), 201


@app.route("/api/environments/<env_id>", methods=["PUT"])
def update_environment(env_id: str):
    payload = request.get_json(force=True) or {}
    envs = _load_environments()
    env = _find_environment(envs, env_id)
    if env is None:
        return jsonify({"error": "not_found"}), 404

    env["name"] = payload.get("name", env.get("name")).strip() or env["name"]
    env["thesis"] = payload.get("thesis", env.get("thesis", "")).strip()
    env["tickers"] = _normalize_tickers(payload.get("tickers", "")) or env.get("tickers", [])
    env["criteria"] = parse_inline_criteria(payload.get("criteria", "")) or env.get("criteria", {})
    env["updated_at"] = _utc_now()
    _save_environments(envs)
    return jsonify(env)


@app.route("/api/environments/<env_id>", methods=["DELETE"])
def delete_environment(env_id: str):
    envs = _load_environments()
    env = _find_environment(envs, env_id)
    if env is None:
        return jsonify({"error": "not_found"}), 404
    envs = [item for item in envs if item.get("id") != env_id]
    _save_environments(envs)
    return jsonify({"status": "deleted"})


@app.route("/api/environments/<env_id>/run", methods=["POST"])
def run_environment(env_id: str):
    envs = _load_environments()
    env = _find_environment(envs, env_id)
    if env is None:
        return jsonify({"error": "not_found"}), 404

    criteria = load_criteria_from_config()
    criteria.update(env.get("criteria") or {})
    tickers = env.get("tickers") or []
    if not tickers:
        return jsonify({"error": "no_tickers"}), 400

    fetcher = DataFetcher()
    screener = StockScreener(criteria, fetcher=fetcher)
    results_df = screener.screen_list(tickers)

    analysis_text = _generate_analysis(results_df)
    report_paths = _write_report(env, results_df, analysis_text)

    env["last_run_at"] = _utc_now()
    env["last_report"] = report_paths
    _save_environments(envs)

    response = {
        "environment": env,
        "summary": {
            "total": len(results_df),
            "passed": int((results_df["status"] == "PASS").sum()) if "status" in results_df else 0,
            "failed": int((results_df["status"] == "FAIL").sum()) if "status" in results_df else 0,
            "analysis": analysis_text,
        },
        "report_paths": report_paths,
        "results": results_df.to_dict(orient="records"),
    }
    return jsonify(response)


def run(host: str = "127.0.0.1", port: int = 5000, debug: bool = False) -> None:
    app.run(host=host, port=port, debug=debug)


if __name__ == "__main__":
    run()
