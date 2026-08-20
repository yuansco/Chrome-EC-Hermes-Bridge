import os
import re
import shutil
import subprocess
from typing import Optional, List
from fastapi import FastAPI, HTTPException
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, Field
import uvicorn

app = FastAPI(title="Chrome-EC Hermes Bridge API", version="1.3.0")

# 允許 Docker 容器透過 host.docker.internal 連線（避免 421 Misdirected Request）
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["localhost", "127.0.0.1", "host.docker.internal", "*"],
)

# === 掛載 MCP (Model Context Protocol) Server ===
try:
    from ec_bridge_mcp import mcp as mcp_server
    # SSE transport: 內部路由為 /sse 和 /messages
    # 掛載於 /mcp → 實際端點: /mcp/sse, /mcp/messages
    app.mount("/mcp", mcp_server.sse_app())
    _mcp_enabled = True
except ImportError:
    _mcp_enabled = False
    print("[WARN] mcp 套件未安裝，MCP 介面已停用。請執行: pip install 'mcp[cli]'")
except Exception as e:
    _mcp_enabled = False
    print(f"[WARN] MCP 掛載失敗: {e}")

# 目錄設定
CHROMIUMOS_DIR = os.path.expanduser("~/chromiumos")
EC_DIR = os.path.join(CHROMIUMOS_DIR, "src/platform/ec")

# Git 白名單指令 (防止 Agent 執行 rm、reset --hard 等破壞性或危險指令)
ALLOWED_GIT_CMDS = {"status", "diff", "log", "show", "branch"}

# === 資料模型 (Pydantic Models) ===

class BuildRequest(BaseModel):
    project: str = Field(..., description="EC Project 名稱，例如: bluey")
    clobber: bool = Field(default=True, description="是否加入 --clobber 清理後重建")
    timeout_seconds: int = Field(default=600, description="編譯超時上限（秒）")

class GitRequest(BaseModel):
    subcommand: str = Field(..., description="Git 子指令，如 status, diff")
    args: List[str] = Field(default=[], description="附加參數，例如 ['--stat'] 或 ['HEAD~1']")
    timeout_seconds: int = Field(default=30, description="執行超時上限（秒）")

class RepoCheckoutRequest(BaseModel):
    cl_number: str = Field(..., description="EC CL (Change List) 編號，例如: 8231407 或 8231407/1")
    timeout_seconds: int = Field(default=300, description="執行超時上限（秒）")

class FlashRequest(BaseModel):
    board: str = Field(default="matsu", description="要燒錄的板子名稱，例如 matsu")
    timeout_seconds: int = Field(default=300, description="燒錄超時上限（秒）")

class DutControlRequest(BaseModel):
    controls: List[str] = Field(
        ...,
        description="一或多個 dut-control 控制指令或查詢項目，例如 ['servo_v4_role:src']、['ec_uart_pty']、['ec_uart_cmd:version']"
    )
    port: Optional[int] = Field(default=None, ge=1, le=65535, description="Servod 連線埠號（預設不指定，由系統使用預設 9999）")
    timeout_seconds: int = Field(default=30, description="執行超時上限（秒）")

class CommandResponse(BaseModel):
    success: bool
    return_code: int
    command: str
    stdout: str
    stderr: str
    error_summary: Optional[str] = None


# === 共用執行函式 ===

def run_command(cmd: List[str], cwd: str, timeout: int) -> CommandResponse:
    if not os.path.isdir(cwd):
        raise HTTPException(status_code=500, detail=f"目錄不存在: {cwd}")
    
    cmd_str = " ".join(cmd)
    try:
        process = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=os.environ.copy() # 繼承使用者的 PATH 等環境變數
        )
        
        return CommandResponse(
            success=(process.returncode == 0),
            return_code=process.returncode,
            command=cmd_str,
            stdout=process.stdout,
            stderr=process.stderr
        )
    except subprocess.TimeoutExpired as e:
        return CommandResponse(
            success=False,
            return_code=-1,
            command=cmd_str,
            stdout=e.stdout or "",
            stderr=e.stderr or "",
            error_summary=f"執行超時（超過 {timeout} 秒）"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"伺服器內部錯誤: {str(e)}")


# === API 端點 ===

@app.get("/api/v1/endpoints", summary="列出所有可用 API 清單 (精簡格式)")
@app.get("/api/v1/list", include_in_schema=False)
def list_endpoints():
    """提供 Agent 快速獲取可用 API 清單與參數格式 (極簡 Token 格式)"""
    return {
        "endpoints": [
            {
                "method": "POST",
                "path": "/api/v1/repo/checkout",
                "desc": "Download & checkout EC CL (repo download chromiumos/platform/ec <cl_number> in ~/chromiumos)",
                "body": {
                    "cl_number*": "str (e.g. 8231407 or 8231407/1)",
                    "timeout_seconds": "int (default=300)"
                }
            },
            {
                "method": "POST",
                "path": "/api/v1/servo/dut-control",
                "desc": "Execute dut-control on host (e.g. dut-control -- servo_v4_role:src)",
                "body": {
                    "controls*": "list[str] (e.g. ['servo_v4_role:src'], ['ec_uart_pty'], ['ec_uart_cmd:version'])",
                    "port": "int (optional servod port)",
                    "timeout_seconds": "int (default=30)"
                }
            },
            {
                "method": "POST",
                "path": "/api/v1/build/ec",
                "desc": "Build EC firmware (zmake build <project> [--clobber])",
                "body": {
                    "project*": "str (e.g. bluey, matsu)",
                    "clobber": "bool (default=true)",
                    "timeout_seconds": "int (default=600)"
                }
            },
            {
                "method": "POST",
                "path": "/api/v1/flash/ec",
                "desc": "Flash EC firmware (flash_ec --board=<board>)",
                "body": {
                    "board": "str (default=matsu)",
                    "timeout_seconds": "int (default=300)"
                }
            },
            {
                "method": "POST",
                "path": "/api/v1/git/command",
                "desc": "Run safe git query in src/platform/ec",
                "body": {
                    "subcommand*": sorted(list(ALLOWED_GIT_CMDS)),
                    "args": "list[str] (default=[])",
                    "timeout_seconds": "int (default=30)"
                }
            },
            {
                "method": "POST",
                "path": "/api/v1/repo/sync",
                "desc": "Sync EC repo (repo sync . in src/platform/ec)",
                "body": None
            },
            {
                "method": "GET",
                "path": "/health",
                "desc": "Health check & workspace dirs",
                "body": None
            },
            {
                "method": "GET",
                "path": "/api/v1/endpoints",
                "desc": "List all endpoints (compact schema for LLM/Agent)",
                "body": None
            }
        ]
    }

@app.post("/api/v1/repo/checkout", response_model=CommandResponse, summary="使用 repo download 下載並切換指定的 EC CL")
@app.post("/api/v1/repo/download", response_model=CommandResponse, include_in_schema=False)
def repo_checkout(req: RepoCheckoutRequest):
    """在 ~/chromiumos 下執行 repo download chromiumos/platform/ec <cl_number>"""
    cl_str = str(req.cl_number).strip()
    if not re.match(r"^[0-9]+(/[0-9]+)?$", cl_str):
        raise HTTPException(status_code=400, detail="無效的 CL 編號格式，應為純數字（如 8231407）或包含 patchset（如 8231407/1）。")
    
    cmd = ["repo", "download", "chromiumos/platform/ec", cl_str]
    print ("cmd=" + str(cmd))
    print ("EC_DIR=" + str(EC_DIR))
    return run_command(cmd, cwd=EC_DIR, timeout=req.timeout_seconds)

@app.post("/api/v1/servo/dut-control", response_model=CommandResponse, summary="執行 dut-control 指令")
@app.post("/api/v1/dut-control", response_model=CommandResponse, include_in_schema=False)
def dut_control(req: DutControlRequest):
    """
    在宿主機直接執行 Servo / DUT 控制指令 (dut-control -- <controls...>)，支援常見指令：
    - servo_v4_role:snk (斷開 DUT 供電) / servo_v4_role:src (供應 DUT 電源)
    - power_state:rec (進入 Recovery Mode)
    - fw_wp_state:force_on (啟用 EC/BIOS 寫入保護) / fw_wp_state:force_off (停用 EC/BIOS 寫入保護)
    - ec_uart_pty / cpu_uart_pty / cr50_uart_pty (查詢 UART 終端 Port)
    - ada_srccaps (取得 ServoV4 USB-PD 供電資訊)
    - ec_uart_cmd:<cmd> (發送 console 指令至 EC，例如 'version')
    - image_usbkey_direction:dut_sees_usbkey / servo_sees_usbkey (切換 USB 隨身碟指向)
    """
    if not req.controls:
        raise HTTPException(status_code=400, detail="controls 不能為空列表。")

    cmd = ["dut-control"]
    if req.port is not None:
        cmd.extend(["-p", str(req.port)])
        
    cmd.append("--")
    cmd.extend(req.controls)
    
    return run_command(cmd, cwd=CHROMIUMOS_DIR, timeout=req.timeout_seconds)

@app.post("/api/v1/build/ec", response_model=CommandResponse)
def build_ec(req: BuildRequest):
    if not re.match(r"^[a-zA-Z0-9_\-]+$", req.project):
        raise HTTPException(status_code=400, detail="無效的 project 名稱。")

    cmd = ["cros_sdk", "--", "zmake", "build", req.project]
    if req.clobber:
        cmd.append("--clobber")

    res = run_command(cmd, cwd=CHROMIUMOS_DIR, timeout=req.timeout_seconds)
    
    # 針對 Build 失敗，嘗試擷取 Error summary
    if not res.success and not res.error_summary:
        combined = res.stderr if res.stderr.strip() else res.stdout
        error_lines = [
            line for line in combined.splitlines() 
            if any(k in line.lower() for k in ["error:", "failed", "fatal:", "error "])
        ]
        res.error_summary = "\n".join(error_lines[-20:]) if error_lines else "編譯失敗，請檢視完整輸出"
        
    return res

@app.post("/api/v1/repo/sync", response_model=CommandResponse)
def repo_sync_ec():
    """在 src/platform/ec 下執行 repo sync . """
    cmd = ["repo", "sync", "."]
    # repo sync 可能需要較長的時間，預設給 600 秒
    return run_command(cmd, cwd=EC_DIR, timeout=600)

@app.post("/api/v1/git/command", response_model=CommandResponse)
def git_command(req: GitRequest):
    """在 src/platform/ec 下執行白名單內的 git 指令"""
    if req.subcommand not in ALLOWED_GIT_CMDS:
        raise HTTPException(
            status_code=403, 
            detail=f"禁止執行該 Git 指令: {req.subcommand}。目前僅允許: {ALLOWED_GIT_CMDS}"
        )
    
    cmd = ["git", req.subcommand] + req.args
    return run_command(cmd, cwd=EC_DIR, timeout=req.timeout_seconds)

@app.post("/api/v1/flash/ec", response_model=CommandResponse)
def flash_ec(req: FlashRequest):
    """執行 cros_sdk flash_ec --board=<board>"""
    if not re.match(r"^[a-zA-Z0-9_\-]+$", req.board):
        raise HTTPException(status_code=400, detail="無效的 board 名稱。")
    # cros_sdk -- flash_ec --zephyr --board=matsu --image=../platform/ec/build/zephyr/matsu/output/ec.bin
    cmd = ["cros_sdk", "--", "flash_ec", "--zephyr", f"--board={req.board}", f"--image=../platform/ec/build/zephyr/{req.board}/output/ec.bin"]
    return run_command(cmd, cwd=CHROMIUMOS_DIR, timeout=req.timeout_seconds)

@app.get("/health")
def health_check():
    return {
        "status": "ok", 
        "chromiumos_dir": CHROMIUMOS_DIR,
        "ec_dir": EC_DIR
    }

if __name__ == "__main__":
    print("==========================================")
    print("  Chrome-EC Hermes Bridge Server v1.3.0  ")
    print("==========================================")
    print(f"  REST API : http://0.0.0.0:8000/api/v1/")
    print(f"  Swagger  : http://0.0.0.0:8000/docs")
    if _mcp_enabled:
        print(f"  MCP(SSE) : http://0.0.0.0:8000/mcp/sse")
    else:
        print(f"  MCP      : DISABLED (mcp package not installed)")
    print("==========================================")
    uvicorn.run(app, host="0.0.0.0", port=8000, forwarded_allow_ips="*")
