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
import pandas as pd
import math

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


@app.after_request
def _disable_cache(response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return response


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


def _generate_analysis(results_df, criteria_count: int) -> str:
    if results_df.empty:
        return "No results were returned. Check tickers and data availability."

    passed = results_df[results_df["status"] == "PASS"]
    failed = results_df[results_df["status"] == "FAIL"]
    avg_pe = results_df["pe_ratio"].dropna().mean()
    avg_roe = results_df["roe"].dropna().mean()
    avg_growth = results_df["revenue_growth"].dropna().mean()

    lines = [
        f"Pass rate: {len(passed)}/{len(results_df)} tickers met all criteria.",
        f"Criteria applied: {criteria_count}.",
    ]
    if criteria_count == 0:
        lines.append("No criteria were configured, so all tickers should pass by default.")
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


def _sanitize_records(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Replace NaN/inf values with None for safe JSON encoding."""
    sanitized: List[Dict[str, Any]] = []
    for record in records:
        clean: Dict[str, Any] = {}
        for key, value in record.items():
            if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
                clean[key] = None
            else:
                clean[key] = value
        sanitized.append(clean)
    return sanitized


def _load_latest_results(env: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Load latest results from the last report JSON file."""
    report = env.get("last_report") or {}
    json_path = report.get("json")
    if not json_path:
        return []
    path = Path(json_path)
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text())
    except Exception:
        return []


def _generate_ai_summary(env: Dict[str, Any], results: List[Dict[str, Any]]) -> Dict[str, str]:
    """Generate a deterministic 'AI' summary based on run results."""
    if not results:
        return {
            "summary": "No prior run data found. Run the environment first.",
            "decision": "No decision possible without results.",
            "confidence": "low",
        }

    df = pd.DataFrame(results)
    passed = df[df.get("status") == "PASS"] if "status" in df.columns else pd.DataFrame()
    failed = df[df.get("status") == "FAIL"] if "status" in df.columns else pd.DataFrame()
    pass_rate = (len(passed) / len(df)) if len(df) else 0

    top_failures = []
    if "failed_criteria" in df.columns:
        top_failures = (
            df["failed_criteria"]
            .dropna()
            .astype(str)
            .str.split(", ")
            .explode()
            .value_counts()
            .head(3)
            .index
            .tolist()
        )

    thesis = env.get("thesis", "").strip()
    thesis_line = f"Thesis: {thesis}" if thesis else "No thesis narrative provided."

    summary_lines = [
        thesis_line,
        f"Pass rate: {len(passed)}/{len(df)} ({pass_rate:.0%}).",
    ]
    if top_failures:
        summary_lines.append("Top misses: " + "; ".join(top_failures) + ".")

    decision = "HOLD"
    confidence = "medium"
    if pass_rate >= 0.6:
        decision = "PROCEED"
        confidence = "medium"
    elif pass_rate <= 0.2:
        decision = "PAUSE"
        confidence = "high"

    return {
        "summary": " ".join(summary_lines),
        "decision": decision,
        "confidence": confidence,
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
        "use_default_criteria": bool(payload.get("use_default_criteria", True)),
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
    if "use_default_criteria" in payload:
        env["use_default_criteria"] = bool(payload.get("use_default_criteria"))
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

    criteria = {}
    if env.get("use_default_criteria", True):
        criteria = load_criteria_from_config()
    criteria.update(env.get("criteria") or {})
    tickers = env.get("tickers") or []
    if not tickers:
        return jsonify({"error": "no_tickers"}), 400

    fetcher = DataFetcher()
    screener = StockScreener(criteria, fetcher=fetcher)
    results_df = screener.screen_list(tickers)
    analysis_text = _generate_analysis(results_df, len(screener.criteria_functions))
    report_paths = _write_report(env, results_df, analysis_text)

    warnings: List[str] = []
    failed_fetch_tickers: List[str] = []
    if len(screener.criteria_functions) == 0:
        warnings.append("No criteria configured. All tickers will pass by default.")
    if "error" in results_df.columns:
        failed_fetch = results_df[results_df["error"] == "data_fetch_failed"]
        if not failed_fetch.empty:
            failed_fetch_tickers = failed_fetch["ticker"].fillna("").tolist()
            warnings.append("Data fetch failed for: " + ", ".join(failed_fetch_tickers))

    env["last_run_at"] = _utc_now()
    env["last_report"] = report_paths
    _save_environments(envs)

    raw_records = results_df.to_dict(orient="records")
    sanitized_records = _sanitize_records(raw_records)
    response = {
        "environment": env,
        "summary": {
            "total": len(results_df),
            "passed": int((results_df["status"] == "PASS").sum()) if "status" in results_df else 0,
            "failed": int((results_df["status"] == "FAIL").sum()) if "status" in results_df else 0,
            "analysis": analysis_text,
            "warnings": warnings,
            "criteria_count": len(screener.criteria_functions),
            "failed_fetch": failed_fetch_tickers,
        },
        "report_paths": report_paths,
        "results": sanitized_records,
    }
    return jsonify(response)


@app.route("/api/environments/<env_id>/ai-summary", methods=["POST"])
def ai_summary(env_id: str):
    envs = _load_environments()
    env = _find_environment(envs, env_id)
    if env is None:
        return jsonify({"error": "not_found"}), 404

    results = _load_latest_results(env)
    summary = _generate_ai_summary(env, results)
    return jsonify(summary)


def run(host: str = "127.0.0.1", port: int = 5000, debug: bool = False) -> None:
    app.run(host=host, port=port, debug=debug)


if __name__ == "__main__":
    run()
