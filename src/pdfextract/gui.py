"""
Browser-based GUI for pdfextract.

Starts a local HTTP server and opens the interface in the default web browser.
No external GUI dependencies are required beyond the Python standard library.

Usage
-----
    python -m pdfextract --gui
    # or via the installed script:
    pdfextract-gui
"""
from __future__ import annotations

import http.server
import json
import os
import socket
import socketserver
import tempfile
import threading
import traceback
import urllib.parse
import webbrowser
from typing import Optional

from . import __version__
from .extractor import PDFExtractor
from .schema import PDFParseError


# ---------------------------------------------------------------------------
# Embedded HTML/CSS/JS interface
# ---------------------------------------------------------------------------

_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>pdfextract {version}</title>
<style>
  *, *::before, *::after {{ box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: #f0f2f5;
    margin: 0;
    padding: 20px;
    color: #1a1a2e;
  }}
  .card {{
    background: #fff;
    border-radius: 12px;
    box-shadow: 0 2px 16px rgba(0,0,0,.08);
    max-width: 900px;
    margin: 0 auto;
    padding: 32px;
  }}
  h1 {{
    margin: 0 0 4px;
    font-size: 1.6rem;
    color: #16213e;
  }}
  .subtitle {{ color: #555; margin: 0 0 28px; font-size: .9rem; }}
  label {{ display: block; font-weight: 600; margin-bottom: 6px; font-size: .9rem; }}
  .row {{ display: flex; gap: 20px; flex-wrap: wrap; margin-bottom: 20px; }}
  .field {{ flex: 1 1 200px; }}
  input[type=file] {{
    display: block;
    width: 100%;
    padding: 10px;
    border: 2px dashed #b0b8c8;
    border-radius: 8px;
    background: #f8f9fb;
    cursor: pointer;
    font-size: .9rem;
  }}
  input[type=file]:hover {{ border-color: #4361ee; }}
  select, input[type=number] {{
    display: block;
    width: 100%;
    padding: 9px 12px;
    border: 1px solid #d0d5dd;
    border-radius: 8px;
    font-size: .9rem;
    background: #fff;
  }}
  .btn {{
    display: inline-flex;
    align-items: center;
    gap: 8px;
    padding: 11px 24px;
    border: none;
    border-radius: 8px;
    font-size: .95rem;
    font-weight: 600;
    cursor: pointer;
    transition: opacity .15s, transform .1s;
  }}
  .btn:active {{ transform: scale(.97); }}
  .btn-primary {{ background: #4361ee; color: #fff; }}
  .btn-primary:hover {{ opacity: .88; }}
  .btn-secondary {{ background: #e8eaf6; color: #4361ee; }}
  .btn-secondary:hover {{ background: #d5d8f3; }}
  .btn:disabled {{ opacity: .45; cursor: not-allowed; transform: none; }}
  .actions {{ display: flex; gap: 12px; margin-bottom: 28px; flex-wrap: wrap; }}
  #status {{
    padding: 10px 14px;
    border-radius: 8px;
    font-size: .88rem;
    margin-bottom: 16px;
    display: none;
  }}
  #status.info {{ background: #e8f4fd; color: #0d6efd; }}
  #status.ok {{ background: #e6f9ee; color: #198754; }}
  #status.error {{ background: #fde8e8; color: #dc3545; }}
  .meta-table {{ width: 100%; border-collapse: collapse; margin-bottom: 20px; font-size: .88rem; }}
  .meta-table th {{ text-align: left; padding: 7px 10px; background: #f8f9fb; color: #555; font-weight: 600; width: 140px; }}
  .meta-table td {{ padding: 7px 10px; border-bottom: 1px solid #f0f0f0; }}
  .stats {{
    display: flex; gap: 16px; margin-bottom: 20px; flex-wrap: wrap;
  }}
  .stat-chip {{
    padding: 6px 14px;
    background: #eef0fd;
    border-radius: 20px;
    font-size: .85rem;
    color: #4361ee;
    font-weight: 600;
  }}
  textarea#output {{
    width: 100%;
    height: 400px;
    font-family: "JetBrains Mono", "Fira Code", Consolas, monospace;
    font-size: .82rem;
    padding: 14px;
    border: 1px solid #d0d5dd;
    border-radius: 8px;
    resize: vertical;
    background: #fafafa;
    line-height: 1.55;
  }}
  .results-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }}
  .results-header h3 {{ margin: 0; font-size: 1rem; }}
  .warn-list {{ font-size: .84rem; color: #856404; background: #fff3cd; padding: 10px 14px; border-radius: 8px; margin-bottom: 14px; }}
  footer {{ text-align: center; margin-top: 24px; font-size: .8rem; color: #999; }}
</style>
</head>
<body>
<div class="card">
  <h1>&#128196; pdfextract</h1>
  <p class="subtitle">Pure-Python PDF text &amp; metadata extractor &mdash; v{version}</p>

  <div class="row">
    <div class="field" style="flex:2 1 300px">
      <label for="pdffile">PDF file</label>
      <input type="file" id="pdffile" accept=".pdf">
    </div>
    <div class="field">
      <label for="fmt">Output format</label>
      <select id="fmt">
        <option value="text">Plain text</option>
        <option value="markdown">Markdown</option>
        <option value="json">JSON</option>
      </select>
    </div>
    <div class="field">
      <label for="maxpages">Max pages <small>(0 = all)</small></label>
      <input type="number" id="maxpages" value="0" min="0">
    </div>
  </div>

  <div class="actions">
    <button class="btn btn-primary" id="extractBtn" onclick="doExtract()" disabled>
      &#9889; Extract
    </button>
    <button class="btn btn-secondary" id="copyBtn" onclick="doCopy()" disabled>
      &#128203; Copy
    </button>
    <button class="btn btn-secondary" id="saveBtn" onclick="doSave()" disabled>
      &#128190; Save
    </button>
  </div>

  <div id="status"></div>

  <div id="metaSection" style="display:none">
    <table class="meta-table" id="metaTable"></table>
    <div class="stats" id="statsRow"></div>
  </div>

  <div id="warnsSection" style="display:none">
    <div class="warn-list" id="warnsList"></div>
  </div>

  <div id="outputSection" style="display:none">
    <div class="results-header">
      <h3>Extracted content</h3>
    </div>
    <textarea id="output" spellcheck="false" readonly></textarea>
  </div>
</div>

<footer>pdfextract {version} &mdash; open a terminal and press Ctrl+C to stop the server</footer>

<script>
document.getElementById('pdffile').addEventListener('change', function() {{
  document.getElementById('extractBtn').disabled = !this.files.length;
}});

let lastOutput = '', lastFilename = '', lastFmt = 'text';

async function doExtract() {{
  const fileInput = document.getElementById('pdffile');
  const fmt = document.getElementById('fmt').value;
  const maxPages = parseInt(document.getElementById('maxpages').value) || 0;

  if (!fileInput.files.length) return;
  const file = fileInput.files[0];

  setStatus('info', '&#9203; Extracting “' + file.name + '”…');
  document.getElementById('extractBtn').disabled = true;

  const arrayBuf = await file.arrayBuffer();
  const url = '/extract?format=' + encodeURIComponent(fmt) + '&max_pages=' + maxPages;

  try {{
    const resp = await fetch(url, {{
      method: 'POST',
      headers: {{ 'Content-Type': 'application/octet-stream' }},
      body: arrayBuf,
    }});
    const data = await resp.json();

    if (data.error) {{
      setStatus('error', '&#10060; ' + data.error);
    }} else {{
      setStatus('ok', '&#10003; Done — ' + data.page_count + ' page(s), ' + data.word_count + ' words');
      lastOutput = data.output;
      lastFilename = file.name.replace(/\\.pdf$/i, '');
      lastFmt = fmt;

      // Metadata table
      const meta = data.metadata || {{}};
      const keys = Object.keys(meta);
      const metaSection = document.getElementById('metaSection');
      if (keys.length) {{
        const rows = keys.map(k => '<tr><th>' + k + '</th><td>' + escHtml(meta[k]) + '</td></tr>').join('');
        document.getElementById('metaTable').innerHTML = rows;
        document.getElementById('statsRow').innerHTML =
          '<span class="stat-chip">&#128196; ' + data.page_count + ' pages</span>' +
          '<span class="stat-chip">&#128221; ' + data.word_count + ' words</span>';
        metaSection.style.display = '';
      }} else {{
        document.getElementById('statsRow').innerHTML =
          '<span class="stat-chip">&#128196; ' + data.page_count + ' pages</span>' +
          '<span class="stat-chip">&#128221; ' + data.word_count + ' words</span>';
        document.getElementById('metaTable').innerHTML = '';
        metaSection.style.display = '';
      }}

      // Warnings
      const warns = data.errors || [];
      const warnsSection = document.getElementById('warnsSection');
      if (warns.length) {{
        document.getElementById('warnsList').innerHTML =
          '<strong>&#9888; Warnings:</strong><br>' + warns.map(escHtml).join('<br>');
        warnsSection.style.display = '';
      }} else {{
        warnsSection.style.display = 'none';
      }}

      document.getElementById('output').value = lastOutput;
      document.getElementById('outputSection').style.display = '';
      document.getElementById('copyBtn').disabled = false;
      document.getElementById('saveBtn').disabled = false;
    }}
  }} catch (e) {{
    setStatus('error', '&#10060; Network error: ' + e.message);
  }} finally {{
    document.getElementById('extractBtn').disabled = false;
  }}
}}

function setStatus(cls, msg) {{
  const el = document.getElementById('status');
  el.className = cls;
  el.innerHTML = msg;
  el.style.display = '';
}}

function escHtml(s) {{
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}}

async function doCopy() {{
  try {{
    await navigator.clipboard.writeText(lastOutput);
    setStatus('ok', '&#10003; Copied to clipboard');
  }} catch (e) {{
    setStatus('error', 'Clipboard access denied');
  }}
}}

function doSave() {{
  const ext = {{ text: 'txt', markdown: 'md', json: 'json' }}[lastFmt] || 'txt';
  const blob = new Blob([lastOutput], {{ type: 'text/plain;charset=utf-8' }});
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = lastFilename + '.' + ext;
  a.click();
  URL.revokeObjectURL(url);
}}
</script>
</body>
</html>
""".format(version=__version__)


# ---------------------------------------------------------------------------
# HTTP request handler
# ---------------------------------------------------------------------------

class _Handler(http.server.BaseHTTPRequestHandler):
    """Minimal HTTP handler for the pdfextract GUI."""

    def log_message(self, fmt: str, *args: object) -> None:  # suppress access log
        pass

    def do_GET(self) -> None:
        if self.path in ("/", "/index.html"):
            body = _HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self._not_found()

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/extract":
            self._not_found()
            return

        qs = urllib.parse.parse_qs(parsed.query)
        fmt = qs.get("format", ["text"])[0]
        max_pages = int(qs.get("max_pages", ["0"])[0] or 0)

        length = int(self.headers.get("Content-Length", 0))
        pdf_bytes = self.rfile.read(length)

        result_dict: dict
        try:
            if not pdf_bytes:
                raise ValueError("Empty file received")

            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp.write(pdf_bytes)
                tmp_path = tmp.name

            try:
                extractor = PDFExtractor(tmp_path, max_pages=max_pages)
                res = extractor.extract()
            finally:
                os.unlink(tmp_path)

            if fmt == "json":
                output = res.to_json()
            elif fmt == "markdown":
                output = res.to_markdown()
            else:
                output = res.full_text

            result_dict = {
                "output": output,
                "page_count": res.page_count,
                "word_count": res.word_count,
                "metadata": res.metadata,
                "errors": res.errors,
            }
        except Exception:  # noqa: BLE001
            result_dict = {"error": traceback.format_exc().splitlines()[-1]}

        body = json.dumps(result_dict, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _not_found(self) -> None:
        self.send_response(404)
        self.end_headers()
        self.wfile.write(b"Not found")


# ---------------------------------------------------------------------------
# Server startup
# ---------------------------------------------------------------------------

def _find_free_port(start: int = 8765) -> int:
    for port in range(start, start + 100):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    return start


def run_gui(port: Optional[int] = None, open_browser: bool = True) -> None:
    """
    Start the pdfextract web GUI.

    Parameters
    ----------
    port : int, optional
        TCP port to listen on (default: first free port starting at 8765).
    open_browser : bool
        Whether to open the system browser automatically.
    """
    port = port or _find_free_port()
    url = f"http://127.0.0.1:{port}"

    # Allow address reuse so the server can restart quickly
    socketserver.TCPServer.allow_reuse_address = True
    server = socketserver.TCPServer(("127.0.0.1", port), _Handler)

    print(f"pdfextract GUI running at {url}")
    print("Press Ctrl+C to stop.")

    if open_browser:
        threading.Timer(0.4, webbrowser.open, args=[url]).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
    finally:
        server.server_close()
