"""
Chrome-EC Hermes Bridge — MCP (Model Context Protocol) Server Module

將現有 REST API 的所有功能映射為 MCP Tools，供支援 MCP 的 AI Agent 直接調用。
本模組共用 ec_bridge_server.py 中的核心執行邏輯（run_command、驗證規則等）。

MCP 端點透過 ec_bridge_server.py 掛載於 /mcp 路徑，與 REST API 共存。
"""

import os
import re
import logging
from typing import Optional

from mcp.server.mcpserver import MCPServer

# ---------------------------------------------------------------------------
# 共用設定 — 與 ec_bridge_server.py 保持一致
# ---------------------------------------------------------------------------
CHROMIUMOS_DIR = os.path.expanduser("~/chromiumos")
EC_DIR = os.path.join(CHROMIUMOS_DIR, "src/platform/ec")
ALLOWED_GIT_CMDS = {"status", "diff", "log", "show", "branch"}

logger = logging.getLogger("ec_bridge_mcp")

# ---------------------------------------------------------------------------
# 初始化 MCP Server
# ---------------------------------------------------------------------------
mcp = MCPServer(
    name="Chrome-EC Hermes Bridge",
    version="1.3.0",
)

# ---------------------------------------------------------------------------
# 共用執行函式 — 直接 import ec_bridge_server 的 run_command
# 由於 MCP Tool 函式不在 FastAPI request context 中，
# HTTPException 無法被 FastMCP 框架正確處理，
# 因此這裡用獨立的包裝函式，將錯誤轉為 dict 回傳。
# ---------------------------------------------------------------------------
import subprocess


def _run_command(cmd: list[str], cwd: str, timeout: int) -> dict:
    """執行系統指令並回傳標準化結果 dict。"""
    if not os.path.isdir(cwd):
        return {
            "success": False,
            "return_code": -1,
            "command": " ".join(cmd),
            "stdout": "",
            "stderr": f"目錄不存在: {cwd}",
            "error_summary": f"目錄不存在: {cwd}",
        }

    cmd_str = " ".join(cmd)
    try:
        process = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=os.environ.copy(),
        )
        return {
            "success": process.returncode == 0,
            "return_code": process.returncode,
            "command": cmd_str,
            "stdout": process.stdout,
            "stderr": process.stderr,
            "error_summary": None,
        }
    except subprocess.TimeoutExpired as e:
        return {
            "success": False,
            "return_code": -1,
            "command": cmd_str,
            "stdout": e.stdout or "",
            "stderr": e.stderr or "",
            "error_summary": f"執行超時（超過 {timeout} 秒）",
        }
    except Exception as e:
        return {
            "success": False,
            "return_code": -1,
            "command": cmd_str,
            "stdout": "",
            "stderr": str(e),
            "error_summary": f"伺服器內部錯誤: {str(e)}",
        }


# ===================================================================
# MCP Tools — 每個 Tool 對應一個 REST API 端點
# ===================================================================


@mcp.tool()
def health_check() -> dict:
    """Check if the Chrome-EC Hermes Bridge server is running and return workspace directory paths.

    Returns:
        dict with keys: status, chromiumos_dir, ec_dir
    """
    return {
        "status": "ok",
        "chromiumos_dir": CHROMIUMOS_DIR,
        "ec_dir": EC_DIR,
    }


@mcp.tool()
def list_endpoints() -> dict:
    """List all available API endpoints with their HTTP methods, descriptions, and request body schemas.

    This is useful for discovering what operations are available on the Bridge server.
    The output is in a compact format optimized for LLM context window efficiency.

    Returns:
        dict with key 'endpoints' containing a list of endpoint descriptors.
    """
    return {
        "endpoints": [
            {
                "method": "POST",
                "path": "/api/v1/repo/checkout",
                "desc": "Download & checkout EC CL (repo download chromiumos/platform/ec <cl_number> in ~/chromiumos)",
                "body": {
                    "cl_number*": "str (e.g. 8231407 or 8231407/1)",
                    "timeout_seconds": "int (default=300)",
                },
            },
            {
                "method": "POST",
                "path": "/api/v1/servo/dut-control",
                "desc": "Execute dut-control on host (e.g. dut-control -- servo_v4_role:src)",
                "body": {
                    "controls*": "list[str] (e.g. ['servo_v4_role:src'], ['ec_uart_pty'], ['ec_uart_cmd:version'])",
                    "port": "int (optional servod port)",
                    "timeout_seconds": "int (default=30)",
                },
            },
            {
                "method": "POST",
                "path": "/api/v1/build/ec",
                "desc": "Build EC firmware (zmake build <project> [--clobber])",
                "body": {
                    "project*": "str (e.g. bluey, matsu)",
                    "clobber": "bool (default=true)",
                    "timeout_seconds": "int (default=600)",
                },
            },
            {
                "method": "POST",
                "path": "/api/v1/flash/ec",
                "desc": "Flash EC firmware (flash_ec --board=<board>)",
                "body": {
                    "board": "str (default=matsu)",
                    "timeout_seconds": "int (default=300)",
                },
            },
            {
                "method": "POST",
                "path": "/api/v1/git/command",
                "desc": "Run safe git query in src/platform/ec",
                "body": {
                    "subcommand*": sorted(list(ALLOWED_GIT_CMDS)),
                    "args": "list[str] (default=[])",
                    "timeout_seconds": "int (default=30)",
                },
            },
            {
                "method": "POST",
                "path": "/api/v1/repo/sync",
                "desc": "Sync EC repo (repo sync . in src/platform/ec)",
                "body": None,
            },
            {
                "method": "GET",
                "path": "/health",
                "desc": "Health check & workspace dirs",
                "body": None,
            },
            {
                "method": "GET",
                "path": "/api/v1/endpoints",
                "desc": "List all endpoints (compact schema for LLM/Agent)",
                "body": None,
            },
        ]
    }


@mcp.tool()
def build_ec(
    project: str,
    clobber: bool = True,
    timeout_seconds: int = 600,
) -> dict:
    """Build EC firmware using zmake inside cros_sdk.

    Executes: cros_sdk -- zmake build <project> [--clobber]

    Args:
        project: EC project name (e.g. 'bluey', 'matsu'). Only alphanumeric, underscore, and hyphen allowed.
        clobber: If True (default), performs a clean rebuild with --clobber flag.
        timeout_seconds: Build timeout in seconds (default: 600).

    Returns:
        CommandResponse dict with keys: success, return_code, command, stdout, stderr, error_summary.
    """
    if not re.match(r"^[a-zA-Z0-9_\-]+$", project):
        return {
            "success": False,
            "return_code": -1,
            "command": "",
            "stdout": "",
            "stderr": "無效的 project 名稱，僅允許英數字、底線、減號。",
            "error_summary": "無效的 project 名稱。",
        }

    cmd = ["cros_sdk", "--", "zmake", "build", project]
    if clobber:
        cmd.append("--clobber")

    res = _run_command(cmd, cwd=CHROMIUMOS_DIR, timeout=timeout_seconds)

    # 針對 Build 失敗，自動擷取 Error summary
    if not res["success"] and not res.get("error_summary"):
        combined = res["stderr"] if res["stderr"].strip() else res["stdout"]
        error_lines = [
            line
            for line in combined.splitlines()
            if any(k in line.lower() for k in ["error:", "failed", "fatal:", "error "])
        ]
        res["error_summary"] = (
            "\n".join(error_lines[-20:]) if error_lines else "編譯失敗，請檢視完整輸出"
        )

    return res


@mcp.tool()
def repo_checkout(
    cl_number: str,
    timeout_seconds: int = 300,
) -> dict:
    """Download and checkout a specific EC CL (Change List) from Gerrit.

    Executes: repo download chromiumos/platform/ec <cl_number> (in ~/chromiumos)

    Args:
        cl_number: The Gerrit CL number, e.g. '8231407' or '8231407/1' (with patchset).
        timeout_seconds: Timeout in seconds (default: 300).

    Returns:
        CommandResponse dict with keys: success, return_code, command, stdout, stderr, error_summary.
    """
    cl_str = str(cl_number).strip()
    if not re.match(r"^[0-9]+(/[0-9]+)?$", cl_str):
        return {
            "success": False,
            "return_code": -1,
            "command": "",
            "stdout": "",
            "stderr": "無效的 CL 編號格式，應為純數字（如 8231407）或包含 patchset（如 8231407/1）。",
            "error_summary": "無效的 CL 編號格式。",
        }

    cmd = ["repo", "download", "chromiumos/platform/ec", cl_str]
    return _run_command(cmd, cwd=EC_DIR, timeout=timeout_seconds)


@mcp.tool()
def repo_sync() -> dict:
    """Sync the EC repository by running 'repo sync .' in src/platform/ec.

    This updates the local EC source code to the latest version. Default timeout is 600 seconds.

    Returns:
        CommandResponse dict with keys: success, return_code, command, stdout, stderr, error_summary.
    """
    cmd = ["repo", "sync", "."]
    return _run_command(cmd, cwd=EC_DIR, timeout=600)


@mcp.tool()
def git_command(
    subcommand: str,
    args: list[str] | None = None,
    timeout_seconds: int = 30,
) -> dict:
    """Execute a safe, whitelisted Git command in the EC source directory (src/platform/ec).

    Only the following Git subcommands are allowed: status, diff, log, show, branch.
    Any other subcommand (e.g. push, reset, checkout) will be rejected.

    Args:
        subcommand: Git subcommand — must be one of: 'status', 'diff', 'log', 'show', 'branch'.
        args: Additional arguments, e.g. ['--stat'], ['-n', '5', '--oneline'], ['HEAD~1'], ['-a'].
        timeout_seconds: Timeout in seconds (default: 30).

    Returns:
        CommandResponse dict with keys: success, return_code, command, stdout, stderr, error_summary.

    Examples:
        git_command(subcommand='status', args=['-s'])
        git_command(subcommand='log', args=['-n', '5', '--oneline'])
        git_command(subcommand='diff', args=['HEAD~1'])
        git_command(subcommand='branch', args=['-a'])
    """
    if subcommand not in ALLOWED_GIT_CMDS:
        return {
            "success": False,
            "return_code": -1,
            "command": "",
            "stdout": "",
            "stderr": f"禁止執行該 Git 指令: {subcommand}。目前僅允許: {sorted(ALLOWED_GIT_CMDS)}",
            "error_summary": f"Git 指令 '{subcommand}' 不在白名單中。",
        }

    cmd = ["git", subcommand] + (args or [])
    return _run_command(cmd, cwd=EC_DIR, timeout=timeout_seconds)


@mcp.tool()
def flash_ec(
    board: str = "matsu",
    timeout_seconds: int = 300,
) -> dict:
    """Flash EC firmware to a physical device using flash_ec via cros_sdk.

    Executes: cros_sdk -- flash_ec --zephyr --board=<board> --image=...

    Args:
        board: Target board name (default: 'matsu'). Only alphanumeric, underscore, and hyphen allowed.
        timeout_seconds: Flash timeout in seconds (default: 300).

    Returns:
        CommandResponse dict with keys: success, return_code, command, stdout, stderr, error_summary.
    """
    if not re.match(r"^[a-zA-Z0-9_\-]+$", board):
        return {
            "success": False,
            "return_code": -1,
            "command": "",
            "stdout": "",
            "stderr": "無效的 board 名稱，僅允許英數字、底線、減號。",
            "error_summary": "無效的 board 名稱。",
        }

    cmd = [
        "cros_sdk",
        "--",
        "flash_ec",
        "--zephyr",
        f"--board={board}",
        f"--image=../platform/ec/build/zephyr/{board}/output/ec.bin",
    ]
    return _run_command(cmd, cwd=CHROMIUMOS_DIR, timeout=timeout_seconds)


@mcp.tool()
def dut_control(
    controls: list[str],
    port: int | None = None,
    timeout_seconds: int = 30,
) -> dict:
    """Execute Servo dut-control commands on the host machine.

    Supports common operations:
    - Power control: servo_v4_role:snk (power off DUT), servo_v4_role:src (power on DUT)
    - Recovery mode: power_state:rec
    - Write protection: fw_wp_state:force_on, fw_wp_state:force_off
    - UART port queries: ec_uart_pty, cpu_uart_pty, cr50_uart_pty
    - USB-PD info: ada_srccaps
    - EC console commands: ec_uart_cmd:<command> (e.g. ec_uart_cmd:version)
    - USB key direction: image_usbkey_direction:dut_sees_usbkey, image_usbkey_direction:servo_sees_usbkey

    Args:
        controls: One or more dut-control commands, e.g. ['servo_v4_role:src'], ['ec_uart_pty', 'cpu_uart_pty'].
        port: Optional servod port number (1-65535). If omitted, uses default port 9999.
        timeout_seconds: Timeout in seconds (default: 30).

    Returns:
        CommandResponse dict with keys: success, return_code, command, stdout, stderr, error_summary.

    Examples:
        dut_control(controls=['servo_v4_role:src'])
        dut_control(controls=['ec_uart_pty', 'cpu_uart_pty', 'cr50_uart_pty'])
        dut_control(controls=['ec_uart_cmd:version'])
    """
    if not controls:
        return {
            "success": False,
            "return_code": -1,
            "command": "",
            "stdout": "",
            "stderr": "controls 不能為空列表。",
            "error_summary": "controls 參數為空。",
        }

    if port is not None and not (1 <= port <= 65535):
        return {
            "success": False,
            "return_code": -1,
            "command": "",
            "stdout": "",
            "stderr": f"無效的 port 號: {port}，應為 1-65535。",
            "error_summary": "無效的 port 號。",
        }

    cmd = ["dut-control"]
    if port is not None:
        cmd.extend(["-p", str(port)])
    cmd.append("--")
    cmd.extend(controls)

    return _run_command(cmd, cwd=CHROMIUMOS_DIR, timeout=timeout_seconds)


# ---------------------------------------------------------------------------
# Standalone 啟動入口（用於 MCP Inspector 開發測試）
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    mcp.run()
