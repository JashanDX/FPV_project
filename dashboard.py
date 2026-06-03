"""
=============================================================
  FPV Detector — Local Web Dashboard
  Run: python dashboard.py
  Open: http://<raspberry-pi-ip>:5000
=============================================================
"""

from flask import Flask, render_template_string, jsonify
import sqlite3
import os

app = Flask(__name__)
DB_PATH = "fpv_results.db"

# ── HTML Template (inline for single-file simplicity) ────────
HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>FPV Detector Dashboard</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: 'Segoe UI', sans-serif;
      background: #0d1117;
      color: #c9d1d9;
      padding: 20px;
    }
    h1 {
      color: #58a6ff;
      font-size: 1.6rem;
      margin-bottom: 4px;
    }
    .subtitle { color: #8b949e; font-size: 0.9rem; margin-bottom: 24px; }
    .stats {
      display: flex;
      gap: 16px;
      flex-wrap: wrap;
      margin-bottom: 28px;
    }
    .stat-card {
      background: #161b22;
      border: 1px solid #30363d;
      border-radius: 10px;
      padding: 16px 24px;
      min-width: 140px;
      text-align: center;
    }
    .stat-card .num {
      font-size: 2rem;
      font-weight: 700;
      margin-bottom: 4px;
    }
    .stat-card .label {
      font-size: 0.8rem;
      color: #8b949e;
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }
    .positive .num { color: #f85149; }
    .negative .num { color: #3fb950; }
    .invalid  .num { color: #d29922; }
    .total    .num { color: #58a6ff; }
    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 0.88rem;
    }
    th {
      background: #161b22;
      color: #8b949e;
      text-align: left;
      padding: 10px 14px;
      font-weight: 600;
      border-bottom: 1px solid #30363d;
    }
    td {
      padding: 10px 14px;
      border-bottom: 1px solid #21262d;
    }
    tr:hover td { background: #161b22; }
    .badge {
      display: inline-block;
      padding: 3px 10px;
      border-radius: 20px;
      font-size: 0.78rem;
      font-weight: 600;
    }
    .POSITIVE { background: #3d1a1a; color: #f85149; border: 1px solid #f85149; }
    .NEGATIVE { background: #122d1b; color: #3fb950; border: 1px solid #3fb950; }
    .INVALID  { background: #2e2416; color: #d29922; border: 1px solid #d29922; }
    .refresh {
      margin-bottom: 16px;
      background: #21262d;
      border: 1px solid #30363d;
      color: #c9d1d9;
      padding: 8px 18px;
      border-radius: 6px;
      cursor: pointer;
      font-size: 0.85rem;
    }
    .refresh:hover { background: #30363d; }
    .empty { text-align: center; color: #8b949e; padding: 40px; }
  </style>
</head>
<body>
  <h1>🐱 FPV Detector Dashboard</h1>
  <p class="subtitle">Feline Panleukopenia Virus — IoT Detection Log</p>

  <div class="stats">
    <div class="stat-card total">
      <div class="num">{{ stats.total }}</div>
      <div class="label">Total Tests</div>
    </div>
    <div class="stat-card positive">
      <div class="num">{{ stats.positive }}</div>
      <div class="label">Positive</div>
    </div>
    <div class="stat-card negative">
      <div class="num">{{ stats.negative }}</div>
      <div class="label">Negative</div>
    </div>
    <div class="stat-card invalid">
      <div class="num">{{ stats.invalid }}</div>
      <div class="label">Invalid</div>
    </div>
  </div>

  <button class="refresh" onclick="location.reload()">⟳  Refresh</button>

  {% if rows %}
  <table>
    <thead>
      <tr>
        <th>#</th>
        <th>Timestamp</th>
        <th>Result</th>
        <th>Device</th>
        <th>Location</th>
        <th>Lines Found</th>
        <th>Alert Sent</th>
      </tr>
    </thead>
    <tbody>
      {% for row in rows %}
      <tr>
        <td>{{ row.id }}</td>
        <td>{{ row.timestamp }}</td>
        <td><span class="badge {{ row.result }}">{{ row.result }}</span></td>
        <td>{{ row.device_id }}</td>
        <td>{{ row.location }}</td>
        <td>{{ row.peaks_found }}</td>
        <td>{{ '✅ Yes' if row.alert_sent else '—' }}</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
  {% else %}
  <div class="empty">No test results yet. Run fpv_detector.py to start scanning.</div>
  {% endif %}

</body>
</html>
"""


def get_results():
    if not os.path.exists(DB_PATH):
        return [], {"total": 0, "positive": 0, "negative": 0, "invalid": 0}
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM results ORDER BY id DESC")
    rows = cursor.fetchall()
    # Stats
    cursor.execute("SELECT COUNT(*) FROM results")
    total = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM results WHERE result='POSITIVE'")
    positive = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM results WHERE result='NEGATIVE'")
    negative = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM results WHERE result='INVALID'")
    invalid = cursor.fetchone()[0]
    conn.close()
    return rows, {
        "total": total,
        "positive": positive,
        "negative": negative,
        "invalid": invalid,
    }


@app.route("/")
def index():
    rows, stats = get_results()
    return render_template_string(HTML, rows=rows, stats=stats)


@app.route("/api/results")
def api_results():
    """JSON API endpoint for external integrations."""
    rows, stats = get_results()
    return jsonify({
        "stats": stats,
        "results": [dict(r) for r in rows]
    })


if __name__ == "__main__":
    print("[DASHBOARD] Starting at http://0.0.0.0:5000")
    app.run(host="0.0.0.0", port=5000, debug=False)
