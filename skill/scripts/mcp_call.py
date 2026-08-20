#!/usr/bin/env python3
"""Generic MCP tool caller for Chrome-EC Hermes Bridge (SSE transport).

Usage:
  python3 mcp_call.py <tool_name> [json_args] [--timeout N] [--list]

Examples:
  python3 mcp_call.py health_check
  python3 mcp_call.py --list
  python3 mcp_call.py repo_sync
  python3 mcp_call.py repo_checkout '{"cl_number": "8231407"}'
  python3 mcp_call.py build_ec '{"project": "matsu", "clobber": true, "timeout_seconds": 1800}' --timeout 2000
  python3 mcp_call.py flash_ec '{"project": "matsu", "timeout_seconds": 1800}' --timeout 2000
  python3 mcp_call.py git_command '{"subcommand": "show", "args": ["--stat", "FETCH_HEAD"]}'
  python3 mcp_call.py dut_control '{"controls": ["ec_uart_pty", "cpu_uart_pty"]}'

Prints the tool result text (JSON) to stdout; exits 1 on error.
Long-running tools (build_ec, flash_ec) block until the server finishes —
pair with terminal background=true when the call may exceed 600s.

Legacy SSE transport: GET /mcp/sse -> event: endpoint -> POST JSON-RPC to
/mcp/messages/?session_id=...  Must send Host: localhost:8000 or uvicorn
rejects with 421. See skill chrome-ec-bridge-mcp for full details.
"""
import http.client
import json
import sys
import threading
import time

HOST = "host.docker.internal"
PORT = 8000
HOST_HEADER = "localhost:8000"  # required by uvicorn host matching
BASE_SSE = "/mcp/sse"

responses = {}
endpoint_path = None
EXPECTED_IDS = set()
done = threading.Event()
lock = threading.Lock()


def handle_event(event_name, data):
    global endpoint_path
    if event_name == "endpoint":
        endpoint_path = data
    elif event_name == "message":
        try:
            msg = json.loads(data)
        except Exception:
            return
        if "id" in msg:
            with lock:
                responses[msg["id"]] = msg
            if all(i in responses for i in EXPECTED_IDS):
                done.set()


def sse_reader(sock_timeout):
    conn = http.client.HTTPConnection(HOST, PORT, timeout=sock_timeout)
    conn.putrequest("GET", BASE_SSE, skip_host=True)  # skip_host: keep custom Host
    conn.putheader("Host", HOST_HEADER)
    conn.putheader("Accept", "text/event-stream")
    conn.endheaders()
    resp = conn.getresponse()
    event_name = "message"
    data_lines = []
    try:
        for raw in resp:
            line = raw.decode("utf-8", "replace").rstrip("\r\n")
            if line == "":
                if data_lines:
                    handle_event(event_name, "\n".join(data_lines))
                event_name = "message"
                data_lines = []
            elif line.startswith("event:"):
                event_name = line[6:].strip()
            elif line.startswith("data:"):
                data_lines.append(line[5:].strip())
    finally:
        conn.close()


def post_json(path, payload):
    body = json.dumps(payload).encode("utf-8")
    conn = http.client.HTTPConnection(HOST, PORT, timeout=30)
    conn.putrequest("POST", path, skip_host=True)  # skip_host: keep custom Host
    conn.putheader("Host", HOST_HEADER)
    conn.putheader("Content-Type", "application/json")
    conn.putheader("Content-Length", str(len(body)))
    conn.endheaders()
    conn.send(body)
    resp = conn.getresponse()
    resp.read()
    status = resp.status
    conn.close()
    return status


def wait_for(pred, timeout):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if pred():
            return True
        time.sleep(0.3)
    return False


def main():
    args = sys.argv[1:]
    list_tools = "--list" in args
    args = [a for a in args if a != "--list"]
    timeout = 120
    if "--timeout" in args:
        i = args.index("--timeout")
        timeout = int(args[i + 1])
        args = args[:i] + args[i + 2:]

    if not list_tools and not args:
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    tool = args[0] if args else None
    tool_args = {}
    if len(args) > 1:
        try:
            tool_args = json.loads(args[1])
            if not isinstance(tool_args, dict):
                raise ValueError("args must be a JSON object")
        except ValueError as e:
            print(f"ERROR: bad JSON args: {e}", file=sys.stderr)
            sys.exit(2)

    global EXPECTED_IDS
    EXPECTED_IDS = {2}
    sock_timeout = max(timeout + 60, 120)
    t = threading.Thread(target=sse_reader, args=(sock_timeout,), daemon=True)
    t.start()

    if not wait_for(lambda: endpoint_path is not None, timeout=30):
        print("FAIL: no SSE endpoint event (Bridge MCP down?)", file=sys.stderr)
        sys.exit(1)

    msg_url = endpoint_path

    # initialize
    st = post_json(msg_url, {
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "hermes-mcp-call", "version": "1.0"},
        },
    })
    if not wait_for(lambda: 1 in responses, timeout=30):
        print("FAIL: no initialize response", file=sys.stderr)
        sys.exit(1)
    if "error" in responses[1]:
        print(f"ERROR: initialize failed: {responses[1]['error']}", file=sys.stderr)
        sys.exit(1)

    # initialized notification
    post_json(msg_url, {"jsonrpc": "2.0", "method": "notifications/initialized"})

    # actual call
    if list_tools:
        method, params = "tools/list", {}
    else:
        method, params = "tools/call", {"name": tool, "arguments": tool_args}
    st = post_json(msg_url, {"jsonrpc": "2.0", "id": 2, "method": method, "params": params})

    if not wait_for(lambda: 2 in responses, timeout=timeout):
        print(f"FAIL: no response for {tool or 'tools/list'} within {timeout}s", file=sys.stderr)
        sys.exit(1)

    msg = responses[2]
    if "error" in msg:
        print(f"ERROR: {json.dumps(msg['error'], ensure_ascii=False)}", file=sys.stderr)
        sys.exit(1)
    result = msg["result"]
    if list_tools:
        for tinfo in result.get("tools", []):
            print(f"- {tinfo['name']}: {tinfo.get('description', '')}")
        return
    if result.get("isError"):
        print(f"ERROR: tool {tool} returned isError=true", file=sys.stderr)
    for item in result.get("content", []):
        print(item.get("text", ""))
    sys.exit(1 if result.get("isError") else 0)


if __name__ == "__main__":
    main()
