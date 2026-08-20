---
name: chrome-ec-bridge-mcp
description: "Use when calling Chrome-EC Bridge MCP tools over SSE."
version: 0.1.0
author: Hermes
platforms: [linux]
metadata:
  hermes:
    tags: [ChromiumOS, EC, MCP, SSE, JSON-RPC, FastAPI, Testing]
---

# Chrome-EC Hermes Bridge MCP (SSE) Client

Call the Chrome-EC Hermes Bridge's MCP tools (`health_check`, `list_endpoints`,
`build_ec`, `repo_checkout`, `repo_sync`, `git_command`, `flash_ec`,
`dut_control`) over the legacy SSE transport, from inside the Docker container.

## When to Use
Use this skill when the user:
- Asks to run `health_check`, `list_endpoints`, `build ec`, `repo checkout`, `repo sync`,
 `git command`, `flash ec` or `dut_control`
- Mentions or requests to **build ec** (e.g., compiling firmware, building the embedded controller target).
- Asks to run **repo sync** or update the source tree for the EC project.
- Requests to **checkout ec** or switch branches/revisions in the EC repository.
- Mentions **dut-control** or needs to interact with, reset, or query the Device Under Test (DUT) hardware state.
- Discusses any workflow related to EC (Embedded Controller) source code management, compilation, or hardware testing.

## Architecture Facts (learned the hard way)
- Bridge FastAPI server runs on the **host** at `host.docker.internal:8000`.
- MCP endpoint: `GET /mcp/sse` (legacy SSE transport, NOT streamable HTTP).
- **Must carry `Host: localhost:8000`** on every request. Connecting with the
  default `host.docker.internal:8000` Host yields **421 Misdirected Request
  / "Invalid Host header"** from uvicorn.
- The SSE stream's first event is `event: endpoint` with
  `data: /mcp/messages/?session_id=<id>` — JSON-RPC messages are POSTed to
  that path.
- **Responses arrive as SSE `message` events on the SAME open SSE connection.**
  The POST itself returns only `202 Accepted` with an empty body.
- Server identifies as `Chrome-EC Hermes Bridge` v1.3.0, protocol `2024-11-05`,
  8 tools (list above).

## Ready-made scripts
- **Generic caller (preferred for everything):** `/opt/data/scripts/mcp_call.py`
  (The mcp_call.py script may be located at either `/opt/data/scripts/mcp_call.py` or `/opt/data/skills/chrome-ec-develop/scripts/mcp_call.py` depending on your environment.). Calls ANY MCP tool:
  ```bash
  python3 /opt/data/scripts/mcp_call.py health_check
  python3 /opt/data/scripts/mcp_call.py --list         # enumerate tools
  python3 /opt/data/scripts/mcp_call.py repo_sync
  python3 /opt/data/scripts/mcp_call.py repo_checkout '{"cl_number": "8231407"}'
  python3 /opt/data/scripts/mcp_call.py build_ec '{"project": "matsu", "clobber": true, "timeout_seconds": 1800}' --timeout 2000
  python3 /opt/data/scripts/mcp_call.py flash_ec '{"project": "matsu", "timeout_seconds": 1800}' --timeout 2000
  python3 /opt/data/scripts/mcp_call.py git_command '{"subcommand": "show", "args": ["--stat", "FETCH_HEAD"]}'
  python3 /opt/data/scripts/mcp_call.py dut_control '{"controls": ["ec_uart_pty", "cpu_uart_pty"]}'
  ```
  It prints the tool result text (the inner JSON, e.g. CommandResponse) to
  stdout and exits non-zero on error. Add `--timeout N` for long-running tools
  (build_ec, flash_ec). For calls likely to exceed the terminal's 600s
  foreground cap, run with `terminal background=true + notify_on_complete=true`
  and poll with `process wait`.
- **Smoke test (health_check + list_endpoints):** `/opt/data/scripts/mcp_bridge_test.py`
  (also at `scripts/mcp_bridge_test.py`) — full handshake on those two tools.

## Procedure (writing a client from scratch)
1. Open `GET /mcp/sse` with `Host: localhost:8000` and **keep it open in a
   reader thread** — this is the channel all responses come back on.
2. Parse SSE frames: `event: endpoint` → `data: /mcp/messages/?session_id=...`.
3. POST JSON-RPC `initialize` to that path; `202` now, result arrives on the
   SSE stream (serverInfo + protocolVersion).
4. POST `notifications/initialized` (id-less notification, also `202`).
5. POST `tools/call` with `{"name": <tool>, "arguments": {}}`, incrementing
   integer ids (e.g. 2, 3, ...).
6. Read SSE `message` events until every expected id has a response; match by
   JSON-RPC `id`. `result.content[0].text` holds the payload (a JSON string).

## Pitfalls
- **`http.client` silently overrides your Host header.** Always call
  `conn.putrequest(method, path, skip_host=True)` then
  `conn.putheader("Host", "localhost:8000")`. Without `skip_host` you get
  421 and think the server is down.
- **Never let the SSE reader thread die.** If it raises or closes the socket,
  the session is invalidated and every subsequent POST 404s (the response
  channel is gone). Wrap parse errors in try/except and define expected ids
  module-level BEFORE starting the thread (a `NameError` inside the reader is
  exactly what kills the session).
- **Don't read the tool result from the POST body** — it's always empty (202).
  The result only exists as an SSE `message` event.
- Plain HTTP to `host.docker.internal` trips the security scanner as HIGH —
  expected for this internal Bridge, not a failure.
- For quick checks, the REST twins return identical data with far less effort:
  `GET /health` ≡ `health_check`, `GET /api/v1/endpoints` ≡ `list_endpoints`.

## Verification
`health_check` returns `{"status": "ok", "chromiumos_dir": ..., "ec_dir": ...}`
and `list_endpoints` returns the 8-endpoint list with `isError: false` on both.
