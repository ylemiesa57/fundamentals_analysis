"""
Minimal Flask app to manage thesis environments and run screenings.
"""

from __future__ import annotations

import html
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
    """
        Disable caching for all responses to prevent stale content.
        
        Args:
            response: Flask response object
            
        Returns:
            Modified Flask response with no-cache headers
        """
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return response


def _utc_now() -> str:
    """Get the current UTC datetime as an ISO format string.
    
    Returns:
        Current UTC datetime in ISO 8601 format
    """
    return datetime.now(timezone.utc).isoformat()


def _load_environments() -> List[Dict[str, Any]]:
    """Load all screening environments from persistent storage.
    
    Returns:
        List of environment dictionaries, or empty list if file doesn't exist
    """
    if not ENVIRONMENTS_PATH.exists():
        return []
    try:
        return json.loads(ENVIRONMENTS_PATH.read_text())
    except Exception:
        return []


def _save_environments(environments: List[Dict[str, Any]]) -> None:
    """Save screening environments to persistent storage.
    
    Args:
        environments: List of environment dictionaries to persist
    """
    ENVIRONMENTS_PATH.write_text(json.dumps(environments, indent=2))


def _find_environment(environments: List[Dict[str, Any]], env_id: str) -> Dict[str, Any] | None:
    """Find a screening environment by its ID.
    
    Args:
        environments: List of environment dictionaries to search
        env_id: UUID of the environment to find
        
    Returns:
        Environment dictionary if found, None otherwise
    """
    for env in environments:
        if env.get("id") == env_id:
            return env
    return None


def _normalize_tickers(raw: str) -> List[str]:
    """Parse and normalize a comma/newline-separated string of ticker symbols.
    
    Handles multiple separators, whitespace, and converts to uppercase.
    
    Args:
        raw: Comma or newline-separated ticker string (e.g., "AAPL,MSFT" or "AAPL\nMSFT")
        
    Returns:
        List of uppercase ticker symbols with whitespace stripped
    """
    if not raw:
        return []
    return [t.strip().upper() for t in raw.replace("\n", ",").split(",") if t.strip()]


def _clean_str(value: Any, default: str = "") -> str:
    """Coerce a possibly-missing/None JSON field into a stripped string.

    Falls back to `default` if the value is missing, explicitly null, or
    blank after stripping. Guards against payloads like {"name": null}
    reaching a bare `.strip()` call and raising an AttributeError.
    """
    if not isinstance(value, str):
        return default
    return value.strip() or default


def _generate_analysis(results_df, criteria_count: int) -> str:
    """Generate a text summary of screening results and metrics.
    
    Produces pass/fail rates, average P/E, ROE, revenue growth, and most
    common failure reasons.
    
    Args:
        results_df: DataFrame containing screening results with columns:
                   status, pe_ratio, roe, revenue_growth, failed_criteria
        criteria_count: Number of criteria applied in this screening
        
    Returns:
        Plain text summary of results
    """
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
    if pd.notna(avg_pe):
        lines.append(f"Average P/E: {avg_pe:.2f}.")
    if pd.notna(avg_roe):
        lines.append(f"Average ROE: {avg_roe:.2%}.")
    if pd.notna(avg_growth):
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


def _build_report_sections(env: Dict[str, Any], results_df, analysis_text: str) -> Dict[str, str]:
    """Build HTML sections for the thesis report.
    
    Creates Overview, Quantitative Health, Risks & Flags, and Decision
    Narrative sections with proper HTML escaping for user-supplied data.
    
    Args:
        env: Environment dictionary with name, thesis, tickers, criteria
        results_df: DataFrame containing screening results
        analysis_text: Plain text analysis summary
        
    Returns:
        Dictionary with keys "overview", "quantitative", "risks", "decision"
        containing formatted HTML content
    """
    # Thesis/name/tickers/criteria are free-text fields the user types into
    # the web UI, and ticker company names come from yfinance (e.g. "AT&T
    # Inc.", "Johnson & Johnson"). None of that is safe to embed directly
    # into the HTML report below -- an unescaped "<" or "&" corrupts the
    # generated page, and an unescaped "<" could inject markup into a
    # report someone else opens in a browser. Escape it all at this HTML
    # boundary (not inside _generate_ai_summary itself, since that function
    # is also used to build the plain-JSON /ai-summary API response).
    thesis = html.escape(env.get("thesis", "").strip()) or "No thesis narrative provided."
    tickers = ", ".join(html.escape(t) for t in (env.get("tickers") or []))
    criteria_items = env.get("criteria") or {}
    criteria_text = ", ".join(
        [f"{html.escape(str(k))}={html.escape(str(v))}" for k, v in criteria_items.items()]
    ) or "None"
    use_defaults = env.get("use_default_criteria", True)
    criteria_mode = "Defaults + custom" if use_defaults else "Custom only"

    total = len(results_df)
    passed = int((results_df["status"] == "PASS").sum()) if "status" in results_df.columns else 0
    failed = total - passed

    fail_reasons = []
    if "failed_criteria" in results_df.columns:
        fail_reasons = (
            results_df["failed_criteria"]
            .dropna()
            .astype(str)
            .str.split(", ")
            .explode()
            .value_counts()
            .head(5)
            .index
            .tolist()
        )

    missing = []
    if "error" in results_df.columns:
        missing = results_df[results_df["error"] == "data_fetch_failed"]["ticker"].dropna().tolist()

    ai_summary = _generate_ai_summary(env, results_df.to_dict(orient="records"))

    overview = f"""
      <p><strong>Thesis</strong>: {thesis}</p>
      <p><strong>Tickers</strong>: {tickers or "None"}</p>
      <p><strong>Criteria</strong>: {criteria_mode} · {criteria_text}</p>
    """

    analysis_text_escaped = html.escape(analysis_text)
    quantitative = f"""
      <p><strong>Pass/Fail</strong>: {passed} passed · {failed} failed · {total} total</p>
      <p>{analysis_text_escaped}</p>
    """

    risks = "<p>No major issues detected.</p>"
    if missing or fail_reasons:
        parts = []
        if missing:
            parts.append(f"Missing data: {', '.join(html.escape(str(m)) for m in missing)}.")
        if fail_reasons:
            parts.append("Common misses: " + "; ".join(html.escape(str(r)) for r in fail_reasons) + ".")
        risks = "<p>" + " ".join(parts) + "</p>"

    decision_text = html.escape(str(ai_summary.get("decision")))
    confidence_text = html.escape(str(ai_summary.get("confidence")))
    summary_text = html.escape(str(ai_summary.get("summary")))
    decision = f"""
      <p><strong>Decision</strong>: {decision_text} · <strong>Confidence</strong>: {confidence_text}</p>
      <p>{summary_text}</p>
    """

    return {
        "overview": overview,
        "quantitative": quantitative,
        "risks": risks,
        "decision": decision,
    }


def _write_report(env: Dict[str, Any], results_df, analysis_text: str) -> Dict[str, str]:
    """Write screening results to CSV, JSON, and HTML report files.
    
    Generates timestamped report files and stores references in the
    environment's last_report field.
    
    Args:
        env: Environment dictionary
        results_df: DataFrame containing screening results
        analysis_text: Plain text analysis summary
        
    Returns:
        Dictionary with keys "run_id", "csv", "json", "html" pointing
        to the generated report files
    """
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    base_name = f"{env['id']}_{timestamp}"
    csv_path = REPORTS_DIR / f"{base_name}.csv"
    json_path = REPORTS_DIR / f"{base_name}.json"
    html_path = REPORTS_DIR / f"{base_name}.html"

    results_df.to_csv(csv_path, index=False)
    json_path.write_text(results_df.to_json(orient="records", indent=2))

    sections = _build_report_sections(env, results_df, analysis_text)
    rows_html = "\n".join(
        [
            "<tr>" + "".join([f"<td>{html.escape(str(value))}</td>" for value in row]) + "</tr>"
            for row in results_df.fillna("").values.tolist()
        ]
    )
    header_html = "".join([f"<th>{html.escape(str(col))}</th>" for col in results_df.columns])
    env_name = html.escape(str(env['name']))
    analysis_text_escaped = html.escape(analysis_text)

    html_path.write_text(
        f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{env_name} Report</title>
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
    .section {{
      margin-bottom: 20px;
      padding: 16px;
      background: white;
      border-radius: 14px;
      border: 1px solid #eee;
    }}
    .section h2 {{
      margin-top: 0;
      font-size: 1.1rem;
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
  <h1>{env_name} Thesis Report</h1>
  <div class="meta">Run ID {base_name} · Generated {datetime.now(timezone.utc).isoformat()}</div>
  <div class="analysis">{analysis_text_escaped}</div>
  <div class="section">
    <h2>Overview</h2>
    {sections["overview"]}
  </div>
  <div class="section">
    <h2>Quantitative Health</h2>
    {sections["quantitative"]}
  </div>
  <div class="section">
    <h2>Risks & Flags</h2>
    {sections["risks"]}
  </div>
  <div class="section">
    <h2>Decision Narrative</h2>
    {sections["decision"]}
  </div>
  <table>
    <thead><tr>{header_html}</tr></thead>
    <tbody>{rows_html}</tbody>
  </table>
</body>
</html>"""
    )

    return {
        "run_id": base_name,
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
    if "failed_criteria" in failed.columns:
        # Only look at rows that actually failed. screener.py writes
        # failed_criteria as '' (empty string, not NaN) for passing
        # rows, so pulling this from the full df let a blank '' entry
        # outrank real failure reasons in value_counts() whenever
        # passes outnumbered fails -- .dropna() never touches it since
        # it isn't NaN, only an empty string.
        top_failures = (
            failed["failed_criteria"]
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
    """
        Serve the main single-page application HTML.
        
        Returns:
            The frontend HTML file (index.html)
        """
    return send_from_directory(app.static_folder, "index.html")


@app.route("/<path:path>")
def static_files(path: str):
    """
        Serve static files (CSS, JavaScript, images) from the static directory.
        
        Args:
            path: Relative path to the static file within static/
            
        Returns:
            The requested static file
        """
    return send_from_directory(app.static_folder, path)


@app.route("/api/environments", methods=["GET"])
def list_environments():
    """
        GET /api/environments - Retrieve all screening environments.
        
        Returns:
            JSON array of environment objects
        """
    return jsonify(_load_environments())


@app.route("/api/environments", methods=["POST"])
def create_environment():
    """
        POST /api/environments - Create a new screening environment.
        
        Expects JSON payload with optional fields:
        - name: Environment name (defaults to "Untitled Thesis")
        - thesis: Investment thesis narrative
        - tickers: Comma/newline-separated ticker symbols
        - criteria: Inline criteria string (e.g., "pe_max=20,roe_min=0.15")
        - use_default_criteria: Boolean to include default config criteria
        
        Returns:
            JSON object of the created environment (201 Created)
        """
    payload = request.get_json(force=True) or {}
    envs = _load_environments()

    env_id = str(uuid.uuid4())
    env = {
        "id": env_id,
        "name": _clean_str(payload.get("name"), "Untitled Thesis"),
        "thesis": _clean_str(payload.get("thesis")),
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
    """
        PUT /api/environments/<env_id> - Update a screening environment.
        
        Updates the environment with provided fields; missing fields retain
        their existing values.
        
        Args:
            env_id: UUID of the environment to update
            
        Expects JSON payload with optional fields (same as create_environment)
        
        Returns:
            JSON object of the updated environment, or 404 if not found
        """
    payload = request.get_json(force=True) or {}
    envs = _load_environments()
    env = _find_environment(envs, env_id)
    if env is None:
        return jsonify({"error": "not_found"}), 404

    env["name"] = _clean_str(payload.get("name"), env.get("name", "Untitled Thesis"))
    env["thesis"] = _clean_str(payload.get("thesis"), env.get("thesis", ""))
    env["tickers"] = _normalize_tickers(payload.get("tickers", "")) or env.get("tickers", [])
    env["criteria"] = parse_inline_criteria(payload.get("criteria", "")) or env.get("criteria", {})
    if "use_default_criteria" in payload:
        env["use_default_criteria"] = bool(payload.get("use_default_criteria"))
    env["updated_at"] = _utc_now()
    _save_environments(envs)
    return jsonify(env)


@app.route("/api/environments/<env_id>", methods=["DELETE"])
def delete_environment(env_id: str):
    """
        DELETE /api/environments/<env_id> - Delete a screening environment.
        
        Args:
            env_id: UUID of the environment to delete
            
        Returns:
            JSON object with status "deleted", or 404 if not found
        """
    envs = _load_environments()
    env = _find_environment(envs, env_id)
    if env is None:
        return jsonify({"error": "not_found"}), 404
    envs = [item for item in envs if item.get("id") != env_id]
    _save_environments(envs)
    return jsonify({"status": "deleted"})


@app.route("/api/environments/<env_id>/run", methods=["POST"])
def run_environment(env_id: str):
    """
        POST /api/environments/<env_id>/run - Execute screening for an environment.
        
        Fetches financial data for configured tickers, applies criteria,
        and generates CSV/JSON/HTML reports.
        
        Args:
            env_id: UUID of the environment to run
            
        Returns:
            JSON object with environment, summary, report_paths, and results,
            or 404/400 if environment not found or has no tickers
        """
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
            "run_id": report_paths.get("run_id"),
        },
        "report_paths": report_paths,
        "results": sanitized_records,
    }
    return jsonify(response)


@app.route("/api/environments/<env_id>/ai-summary", methods=["POST"])
def ai_summary(env_id: str):
    """
        POST /api/environments/<env_id>/ai-summary - Get decision summary for last run.
        
        Loads results from the last screening run and generates a deterministic
        decision (PROCEED/HOLD/PAUSE) with confidence level.
        
        Args:
            env_id: UUID of the environment
            
        Returns:
            JSON object with keys "summary", "decision", "confidence",
            or 404 if environment not found
        """
    envs = _load_environments()
    env = _find_environment(envs, env_id)
    if env is None:
        return jsonify({"error": "not_found"}), 404

    results = _load_latest_results(env)
    summary = _generate_ai_summary(env, results)
    return jsonify(summary)


def run(host: str = "127.0.0.1", port: int = 5000, debug: bool = False) -> None:
    """Start the Flask development server.
    
    Args:
        host: Host to bind to (default 127.0.0.1)
        port: Port to bind to (default 5000)
        debug: Whether to run in debug mode (default False)
    """
    app.run(host=host, port=port, debug=debug)


if __name__ == "__main__":
    run()
