# Hermes Agent MCP 整合指南

[![MCP](https://img.shields.io/badge/MCP-Model%20Context%20Protocol-blueviolet.svg?style=flat)](https://modelcontextprotocol.io)
[![FastMCP](https://img.shields.io/badge/FastMCP-Python%20SDK-009688.svg?style=flat)](https://gofastmcp.com)

本文件說明如何讓 **Hermes Agent**（或其他支援 MCP 的 AI Agent）透過 **Model Context Protocol (MCP)** 介面連接並調用 Chrome-EC Hermes Bridge 的完整工具鏈。

---

## 目錄
- [為什麼使用 MCP？](#為什麼使用-mcp)
- [系統架構總覽](#系統架構總覽)
- [前置準備](#前置準備)
- [Bridge Server 啟動方式](#bridge-server-啟動方式)
- [MCP 連線方式](#mcp-連線方式)
  - [方式 A：Streamable HTTP（推薦）](#方式-a-streamable-http推薦)
  - [方式 B：STDIO（本機開發測試）](#方式-b-stdio本機開發測試)
- [Docker 容器環境設定](#docker-容器環境設定)
- [MCP Tools 完整清單](#mcp-tools-完整清單)
  - [health_check](#1-health_check)
  - [list_endpoints](#2-list_endpoints)
  - [build_ec](#3-build_ec)
  - [repo_checkout](#4-repo_checkout)
  - [repo_sync](#5-repo_sync)
  - [git_command](#6-git_command)
  - [flash_ec](#7-flash_ec)
  - [dut_control](#8-dut_control)
- [Python Client 呼叫範例](#python-client-呼叫範例)
- [Hermes Agent 設定檔範例](#hermes-agent-設定檔範例)
- [MCP Inspector 開發測試](#mcp-inspector-開發測試)
- [REST API 與 MCP 對照表](#rest-api-與-mcp-對照表)
- [常見問題與除錯 (FAQ)](#常見問題與除錯-faq)

---

## 為什麼使用 MCP？

**Model Context Protocol (MCP)** 是由 Anthropic 發起的開放標準，定義了 AI Agent 與外部工具之間的通用介面規範。

### MCP 相較傳統 REST API 的優勢

| 特性 | REST API | MCP |
|:---|:---|:---|
| **工具發現** | 需要先呼叫 `GET /api/v1/endpoints` 取得清單 | Agent 自動透過 MCP 協議發現所有可用 Tools |
| **參數型別** | Agent 需要解析 JSON Schema 文件 | 自動從 Python Type Hints 生成 JSON Schema |
| **整合成本** | 需自行撰寫 HTTP Client 封裝 | Agent 框架原生支援，零代碼整合 |
| **標準化** | 每個服務定義不同 | 統一的 MCP 協議，跨服務通用 |
| **錯誤處理** | HTTP Status Code + 自定義格式 | MCP 標準錯誤回報機制 |

> **重點：使用 MCP 後，Hermes Agent 只需在設定檔中加入 Bridge 的 MCP 端點，即可自動獲得所有 EC 開發工具能力，無需額外撰寫任何 API Client 程式碼。**

---

## 系統架構總覽

```
┌───────────────────────────────────────────────────────┐
│                Docker 容器                             │
│  ┌────────────────────────────────────────────────┐   │
│  │             Hermes Agent                       │   │
│  │                                                │   │
│  │  ┌──────────┐    ┌──────────────────────────┐  │   │
│  │  │ MCP      │    │ REST API Client          │  │   │
│  │  │ Client   │    │ (ECBridgeClient)         │  │   │
│  │  └────┬─────┘    └──────────┬───────────────┘  │   │
│  └───────│─────────────────────│──────────────────┘   │
│          │                     │                      │
└──────────│─────────────────────│──────────────────────┘
           │ MCP (Streamable HTTP)  │ REST (HTTP POST/GET)
           │                     │
    ───────│─────────────────────│──── host.docker.internal:8000
           │                     │
┌──────────│─────────────────────│──────────────────────┐
│          ▼                     ▼         宿主機        │
│  ┌─────────────────────────────────────────────────┐  │
│  │       ec_bridge_server.py (FastAPI + Uvicorn)   │  │
│  │                                                 │  │
│  │   /mcp              /api/v1/*        /docs      │  │
│  │     │                   │               │       │  │
│  │     ▼                   ▼               ▼       │  │
│  │  ec_bridge_mcp.py   REST Handlers   Swagger UI  │  │
│  │  (FastMCP Tools)    (FastAPI)                   │  │
│  │     │                   │                       │  │
│  │     └───────┬───────────┘                       │  │
│  │             ▼                                   │  │
│  │     共用核心執行邏輯                               │  │
│  │   (subprocess → cros_sdk / git / dut-control)   │  │
│  └─────────────────────────────────────────────────┘  │
│                        │                              │
│                        ▼                              │
│          ChromiumOS 開發工具鏈 & 硬體                   │
│    (cros_sdk, zmake, flash_ec, repo, Servo/DUT)       │
└───────────────────────────────────────────────────────┘
```

---

## 前置準備

### 1. 宿主機環境

確保已完成以下設定（詳見 [chrome_ec_hermes_bridge_api.md](chrome_ec_hermes_bridge_api.md)）：

- ChromiumOS 原始碼已同步至 `~/chromiumos`
- 免密碼 sudo 已設定
- Python 3.10+ 已安裝

### 2. 安裝 MCP 依賴

```bash
# 在 Bridge 專案目錄下
pip install -r requirements.txt

# 或手動安裝 MCP SDK
pip install "mcp[cli]>=1.0.0"
```

### 3. 驗證安裝

```bash
python -c "from mcp.server.fastmcp import FastMCP; print('MCP SDK OK')"
python -c "from ec_bridge_mcp import mcp; print('MCP Module OK')"
```

---

## Bridge Server 啟動方式

啟動指令，MCP 會自動掛載：

```bash
# 方法一：使用腳本（推薦）
./run.sh

# 方法二：手動啟動
source venv/bin/activate
python ec_bridge_server.py
```

啟動後會看到：

```
==========================================
  Chrome-EC Hermes Bridge Server v1.3.0
==========================================
  REST API : http://0.0.0.0:8000/api/v1/
  Swagger  : http://0.0.0.0:8000/docs
  MCP      : http://0.0.0.0:8000/mcp
==========================================
```

伺服器同時提供兩種介面：
- **REST API**：`http://0.0.0.0:8000/api/v1/*`
- **MCP**：`http://0.0.0.0:8000/mcp/sse`

---

## MCP 連線方式

### 方式 A：Streamable HTTP（推薦）

適用於 Agent 運行在 Docker 容器中、遠端伺服器、或任何網路可達的環境。

**MCP 端點 URL**：
```
http://host.docker.internal:8000/mcp/sse
```

若從宿主機本地連線：
```
http://localhost:8000/mcp/sse
```

### 方式 B：STDIO（本機開發測試）

適用於 Agent 與 Bridge 在同一台機器上進行開發測試。可用 `mcp` CLI 直接啟動 STDIO 模式的 MCP Server：

```bash
# 在 Bridge 專案目錄下
mcp run ec_bridge_mcp.py
```

或使用 Python 直接執行：
```bash
python ec_bridge_mcp.py
```

> **注意**：STDIO 模式下 Server 透過 stdin/stdout 通訊，不會啟動 HTTP 伺服器。此模式適合本機開發測試，不適合 Docker 跨容器場景。

---

## Docker 容器環境設定

### Docker Run

```bash
docker run -it \
  --add-host=host.docker.internal:host-gateway \
  <IMAGE_NAME> bash
```

### Docker Compose

```yaml
services:
  hermes-agent:
    image: <IMAGE_NAME>
    extra_hosts:
      - "host.docker.internal:host-gateway"
    environment:
      - EC_BRIDGE_MCP_URL=http://host.docker.internal:8000/mcp/sse
```

---

## MCP Tools 完整清單

Bridge MCP Server 提供以下 8 個 Tools，Agent 可透過 MCP 協議自動發現並呼叫：

### 1. health_check

| 屬性 | 值 |
|:---|:---|
| **Tool 名稱** | `health_check` |
| **說明** | 檢查 Bridge 伺服器運行狀態及 ChromiumOS 目錄配置 |
| **參數** | 無 |

**回傳範例**：
```json
{
  "status": "ok",
  "chromiumos_dir": "/home/yuan/chromiumos",
  "ec_dir": "/home/yuan/chromiumos/src/platform/ec"
}
```

---

### 2. list_endpoints

| 屬性 | 值 |
|:---|:---|
| **Tool 名稱** | `list_endpoints` |
| **說明** | 列出所有可用 API 端點（精簡 Token 格式），適合 Agent 啟動時發現可用操作 |
| **參數** | 無 |

---

### 3. build_ec

| 屬性 | 值 |
|:---|:---|
| **Tool 名稱** | `build_ec` |
| **說明** | 在 `cros_sdk` 環境中執行 `zmake build` 編譯 EC 韌體 |
| **底層指令** | `cros_sdk -- zmake build <project> [--clobber]` |

**參數**：

| 參數名 | 型態 | 必填 | 預設值 | 說明 |
|:---|:---|:---|:---|:---|
| `project` | `str` | **是** | — | EC Project 名稱（如 `bluey`、`matsu`） |
| `clobber` | `bool` | 否 | `True` | 是否全清理重建 |
| `timeout_seconds` | `int` | 否 | `600` | 編譯超時上限（秒） |

**回傳格式（CommandResponse）**：
```json
{
  "success": true,
  "return_code": 0,
  "command": "cros_sdk -- zmake build bluey --clobber",
  "stdout": "Build succeeded...",
  "stderr": "",
  "error_summary": null
}
```

---

### 4. repo_checkout

| 屬性 | 值 |
|:---|:---|
| **Tool 名稱** | `repo_checkout` |
| **說明** | 使用 `repo download` 下載並切換至指定的 EC Gerrit CL |
| **底層指令** | `repo download chromiumos/platform/ec <cl_number>` |

**參數**：

| 參數名 | 型態 | 必填 | 預設值 | 說明 |
|:---|:---|:---|:---|:---|
| `cl_number` | `str` | **是** | — | Gerrit CL 編號（如 `8231407` 或 `8231407/1`） |
| `timeout_seconds` | `int` | 否 | `300` | 超時上限（秒） |

---

### 5. repo_sync

| 屬性 | 值 |
|:---|:---|
| **Tool 名稱** | `repo_sync` |
| **說明** | 在 EC 目錄執行 `repo sync .` 同步程式碼至最新版 |
| **底層指令** | `repo sync .`（在 `src/platform/ec` 下執行） |
| **參數** | 無 |
| **超時** | 預設 600 秒 |

---

### 6. git_command

| 屬性 | 值 |
|:---|:---|
| **Tool 名稱** | `git_command` |
| **說明** | 在 EC 目錄執行白名單內的安全 Git 查詢指令 |
| **白名單** | `status`, `diff`, `log`, `show`, `branch` |

**參數**：

| 參數名 | 型態 | 必填 | 預設值 | 說明 |
|:---|:---|:---|:---|:---|
| `subcommand` | `str` | **是** | — | Git 子指令（必須在白名單內） |
| `args` | `list[str]` | 否 | `[]` | 附加參數，如 `["--stat"]`, `["-n", "5"]` |
| `timeout_seconds` | `int` | 否 | `30` | 超時上限（秒） |

**使用範例**：
```
git_command(subcommand="status", args=["-s"])
git_command(subcommand="log", args=["-n", "5", "--oneline"])
git_command(subcommand="diff", args=["HEAD~1"])
git_command(subcommand="branch", args=["-a"])
```

---

### 7. flash_ec

| 屬性 | 值 |
|:---|:---|
| **Tool 名稱** | `flash_ec` |
| **說明** | 透過 `cros_sdk` 執行 `flash_ec` 將韌體燒錄至開發板 |
| **底層指令** | `cros_sdk -- flash_ec --zephyr --board=<board> --image=...` |

**參數**：

| 參數名 | 型態 | 必填 | 預設值 | 說明 |
|:---|:---|:---|:---|:---|
| `board` | `str` | 否 | `matsu` | 目標板名稱 |
| `timeout_seconds` | `int` | 否 | `300` | 燒錄超時上限（秒） |

---

### 8. dut_control

| 屬性 | 值 |
|:---|:---|
| **Tool 名稱** | `dut_control` |
| **說明** | 在宿主機執行 Servo `dut-control` 指令，控制 DUT 電源、UART、寫保護等 |
| **底層指令** | `dut-control [-p <port>] -- <controls...>` |

**參數**：

| 參數名 | 型態 | 必填 | 預設值 | 說明 |
|:---|:---|:---|:---|:---|
| `controls` | `list[str]` | **是** | — | 一或多個控制項 |
| `port` | `int` | 否 | `null` | Servod 連線埠號 (1-65535) |
| `timeout_seconds` | `int` | 否 | `30` | 超時上限（秒） |

**常用 controls 值**：

| 控制項 | 說明 |
|:---|:---|
| `servo_v4_role:snk` | 斷開 DUT 供電 |
| `servo_v4_role:src` | 供應 DUT 電源 |
| `power_state:rec` | 進入 Recovery 模式 |
| `fw_wp_state:force_on` | 啟用韌體寫入保護 |
| `fw_wp_state:force_off` | 停用韌體寫入保護 |
| `ec_uart_pty` | 查詢 EC UART Port |
| `cpu_uart_pty` | 查詢 CPU UART Port |
| `cr50_uart_pty` | 查詢 Cr50/GSC UART Port |
| `ada_srccaps` | 查詢 USB-PD 供電資訊 |
| `ec_uart_cmd:<cmd>` | 發送 Console 指令至 EC |
| `image_usbkey_direction:dut_sees_usbkey` | USB 隨身碟指向 DUT |
| `image_usbkey_direction:servo_sees_usbkey` | USB 隨身碟指向 Servo |

---

## Python Client 呼叫範例

以下範例展示如何在 Hermes Agent 的 Python 環境中使用 MCP Client SDK 連接 Bridge：

### 安裝 MCP Client SDK

```bash
pip install "mcp[cli]>=1.0.0"
```

### 基本呼叫範例

```python
import asyncio
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

async def main():
    # 連接至 Bridge MCP Server
    async with streamablehttp_client("http://host.docker.internal:8000/mcp") as (
        read_stream,
        write_stream,
        _,
    ):
        async with ClientSession(read_stream, write_stream) as session:
            # 初始化 MCP 連線
            await session.initialize()

            # 1. 自動發現所有可用 Tools
            tools = await session.list_tools()
            print("Available MCP Tools:")
            for tool in tools.tools:
                print(f"  - {tool.name}: {tool.description[:60]}...")

            # 2. 健康檢查
            result = await session.call_tool("health_check", {})
            print(f"\nHealth: {result.content[0].text}")

            # 3. 查詢 Git 狀態
            result = await session.call_tool("git_command", {
                "subcommand": "status",
                "args": ["-s"],
            })
            print(f"\nGit Status: {result.content[0].text}")

            # 4. 編譯 EC 韌體
            result = await session.call_tool("build_ec", {
                "project": "bluey",
                "clobber": True,
                "timeout_seconds": 600,
            })
            print(f"\nBuild Result: {result.content[0].text}")

            # 5. 查詢 UART Port
            result = await session.call_tool("dut_control", {
                "controls": ["ec_uart_pty", "cpu_uart_pty"],
            })
            print(f"\nUART Ports: {result.content[0].text}")

            # 6. 下載指定 CL
            result = await session.call_tool("repo_checkout", {
                "cl_number": "8231407",
            })
            print(f"\nCheckout: {result.content[0].text}")

if __name__ == "__main__":
    asyncio.run(main())
```

### 完整 Debug 工作流程範例

```python
import asyncio
import json
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

async def ec_debug_workflow():
    """模擬 Hermes Agent 的完整 EC Debug 工作流程"""

    async with streamablehttp_client("http://host.docker.internal:8000/mcp") as (
        read_stream,
        write_stream,
        _,
    ):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            # Step 1: 確認連線
            health = await session.call_tool("health_check", {})
            print("✅ Bridge 連線正常")

            # Step 2: 切換到指定 CL
            checkout = await session.call_tool("repo_checkout", {
                "cl_number": "8231407",
            })
            data = json.loads(checkout.content[0].text)
            if data["success"]:
                print(f"✅ 已切換至 CL 8231407")
            else:
                print(f"❌ CL 切換失敗: {data['stderr']}")
                return

            # Step 3: 檢視變更內容
            diff = await session.call_tool("git_command", {
                "subcommand": "diff",
                "args": ["--stat"],
            })
            print(f"📄 變更檔案:\n{json.loads(diff.content[0].text)['stdout']}")

            # Step 4: 編譯
            print("🔨 開始編譯 bluey...")
            build = await session.call_tool("build_ec", {
                "project": "bluey",
                "clobber": False,
                "timeout_seconds": 600,
            })
            build_data = json.loads(build.content[0].text)
            if build_data["success"]:
                print("✅ 編譯成功")
            else:
                print(f"❌ 編譯失敗:\n{build_data['error_summary']}")
                return

            # Step 5: 供電 DUT
            await session.call_tool("dut_control", {
                "controls": ["servo_v4_role:src"],
            })
            print("⚡ DUT 已供電")

            # Step 6: 燒錄韌體
            print("📥 開始燒錄...")
            flash = await session.call_tool("flash_ec", {
                "board": "bluey",
                "timeout_seconds": 300,
            })
            flash_data = json.loads(flash.content[0].text)
            if flash_data["success"]:
                print("✅ 燒錄成功")
            else:
                print(f"❌ 燒錄失敗: {flash_data['stderr']}")
                return

            # Step 7: 驗證 EC 版本
            version = await session.call_tool("dut_control", {
                "controls": ["ec_uart_cmd:version"],
            })
            print(f"📋 EC 版本:\n{json.loads(version.content[0].text)['stdout']}")

            print("\n🎉 Debug 工作流程完成！")

if __name__ == "__main__":
    asyncio.run(ec_debug_workflow())
```

---

## Hermes Agent 設定檔範例

### 方式 A：Streamable HTTP 遠端連線（推薦）

在 Hermes Agent 的 MCP 設定檔中加入以下配置：

```json
{
  "mcpServers": {
    "chrome-ec-bridge": {
      "url": "http://host.docker.internal:8000/mcp",
      "transport": "streamable-http"
    }
  }
}
```

### 方式 B：STDIO 本機連線

若 Agent 與 Bridge 在同一台機器：

```json
{
  "mcpServers": {
    "chrome-ec-bridge": {
      "command": "python",
      "args": ["/path/to/Chrome-EC-Hermes-Bridge/ec_bridge_mcp.py"],
      "transport": "stdio"
    }
  }
}
```

### 方式 C：使用 uv 管理環境

```json
{
  "mcpServers": {
    "chrome-ec-bridge": {
      "command": "uv",
      "args": [
        "run",
        "--directory", "/path/to/Chrome-EC-Hermes-Bridge",
        "ec_bridge_mcp.py"
      ],
      "transport": "stdio"
    }
  }
}
```

---

## MCP Inspector 開發測試

MCP Inspector 是一個瀏覽器端的互動式測試工具，可讓您快速驗證所有 MCP Tools 的功能。

### 啟動 Inspector

```bash
# 在 Bridge 專案目錄下
mcp dev ec_bridge_mcp.py
```

啟動後會自動在瀏覽器開啟 MCP Inspector UI，可以：
1. 瀏覽所有 Tool 定義與參數 Schema
2. 直接呼叫任意 Tool 並查看回傳結果
3. 即時檢視 MCP 協議通訊內容

---

## REST API 與 MCP 對照表

| REST API 端點 | HTTP 方法 | MCP Tool 名稱 | 備註 |
|:---|:---|:---|:---|
| `/health` | GET | `health_check` | — |
| `/api/v1/endpoints` | GET | `list_endpoints` | — |
| `/api/v1/build/ec` | POST | `build_ec` | — |
| `/api/v1/repo/checkout` | POST | `repo_checkout` | 含別名 `/api/v1/repo/download` |
| `/api/v1/repo/sync` | POST | `repo_sync` | — |
| `/api/v1/git/command` | POST | `git_command` | 白名單保護 |
| `/api/v1/flash/ec` | POST | `flash_ec` | — |
| `/api/v1/servo/dut-control` | POST | `dut_control` | 含別名 `/api/v1/dut-control` |

> **兩種介面功能完全等價**，底層共用相同的執行邏輯。您可以根據 Agent 的能力選擇使用 REST API 或 MCP。

---

## 常見問題與除錯 (FAQ)

### Q1: 如何確認 MCP 介面是否正常啟動？

啟動 Bridge Server 後，查看終端輸出，確認有以下訊息：
```
  MCP      : http://0.0.0.0:8000/mcp
```

若顯示 `DISABLED`，表示 `mcp` 套件未安裝，請執行：
```bash
pip install "mcp[cli]>=1.0.0"
```

### Q2: Docker 容器內無法連線到 MCP 端點

**原因**：容器內未正確解析宿主機 IP。

**解法**：啟動容器時加入 `--add-host=host.docker.internal:host-gateway`：
```bash
docker run -it --add-host=host.docker.internal:host-gateway <IMAGE> bash
```

### Q3: MCP Client 呼叫 Tool 時出現 Timeout

**原因**：EC 編譯或 repo sync 等操作耗時超過 MCP Client 預設超時。

**解法**：
1. 在呼叫 `build_ec` 時調大 `timeout_seconds` 參數（例如 1200）
2. 同時確認 MCP Client SDK 的連線超時設定足夠大

### Q4: 可以同時使用 REST API 和 MCP 嗎？

**可以。** 兩種介面共存於同一個伺服器進程，互不干擾：
- REST API：`http://host.docker.internal:8000/api/v1/*`
- MCP：`http://host.docker.internal:8000/mcp`

### Q5: MCP Inspector 顯示 Connection Refused

**原因**：Inspector 嘗試連線 STDIO 模式的 Server，而非 HTTP 模式。

**解法**：確保使用以下指令啟動（不要手動指定 transport）：
```bash
mcp dev ec_bridge_mcp.py
```

### Q6: 如何查看 MCP 通訊的原始 JSON-RPC 訊息？

使用 MCP Inspector（`mcp dev ec_bridge_mcp.py`），介面中可即時查看所有 JSON-RPC request / response。

---

## 附錄：MCP 協議簡介

MCP (Model Context Protocol) 定義了三種核心抽象：

| 概念 | 說明 | 本 Bridge 使用情況 |
|:---|:---|:---|
| **Tools** | Agent 可主動呼叫的操作（類似函式） | ✅ 所有 8 個端點皆實作為 Tools |
| **Resources** | Agent 可讀取的靜態或動態資料來源 | — 未使用（未來可擴展） |
| **Prompts** | 預定義的提示詞模板 | — 未使用（未來可擴展） |

MCP 支援兩種傳輸方式：
- **STDIO**：透過 stdin/stdout 通訊，適合本機子行程
- **Streamable HTTP**：透過 HTTP POST 通訊，適合網路/Docker 場景（本 Bridge 推薦方式）
