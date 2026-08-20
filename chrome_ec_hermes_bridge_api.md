# Chrome-EC Hermes Bridge API

[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009688.svg?style=flat&logo=FastAPI&logoColor=white)](https://fastapi.tiangolo.com)
[![MCP](https://img.shields.io/badge/MCP-Model%20Context%20Protocol-blueviolet.svg?style=flat)](https://modelcontextprotocol.io)
[![Python](https://img.shields.io/badge/Python-3.10+-3776AB.svg?style=flat&logo=Python&logoColor=white)](https://www.python.org/)

**Chrome-EC Hermes Bridge API** 是一個基於 FastAPI 的輕量級橋接伺服器，旨在提供標準化 HTTP REST API 及 **MCP (Model Context Protocol)** 介面，供外部系統或運行於 **Docker 容器中的 AI Agent（如 Hermes）** 調用 ChromiumOS 宿主機環境的 Chrome-EC 開發工具鏈（包含 `cros_sdk`、`zmake` 編譯、`flash_ec` 燒錄、`repo sync` 同步及受白名單保護的 Git 操作）。

---

## 快速導覽目錄
- [環境前置設定 (免密碼 sudo)](#環境前置設定)
- [系統架構與預設路徑](#系統架構與預設路徑)
- [伺服器啟動方式](#伺服器啟動方式)
- [Docker 容器連線設定 (host.docker.internal)](#docker-容器連線設定-hostdockerinternal)
- [共用資料結構 (Data Models)](#共用資料結構-data-models)
- [API 端點詳細清單](#api-端點詳細清單)
  - [1. 查詢可用 API 清單 (GET /api/v1/endpoints) - Agent 專用](#1-查詢可用-api-清單-get-apiv1endpoints---agent-專用)
  - [2. 伺服器健康檢查 (GET /health)](#2-伺服器健康檢查-get-health)
  - [3. EC 韌體編譯 (POST /api/v1/build/ec)](#3-ec-韌體編譯-post-apiv1buildec)
  - [4. 切換與下載指定 EC CL (POST /api/v1/repo/checkout)](#4-切換與下載指定-ec-cl-post-apiv1repocheckout)
  - [5. 同步 EC 程式庫 (POST /api/v1/repo/sync)](#5-同步-ec-程式庫-post-apiv1reposync)
  - [6. 執行 Git 查詢指令 (POST /api/v1/git/command)](#6-執行-git-查詢指令-post-apiv1gitcommand)
  - [7. EC 韌體燒錄 (POST /api/v1/flash/ec)](#7-ec-韌體燒錄-post-apiv1flashec)
  - [8. Servo / DUT 控制 (POST /api/v1/servo/dut-control)](#8-servo--dut-控制-post-apiv1servodut-control)
- [Docker 內 Python 呼叫範例代碼](#docker-內-python-呼叫範例代碼)
- [MCP (Model Context Protocol) 介面](#mcp-model-context-protocol-介面)
- [安全性與 Git 白名單機制](#安全性與-git-白名單機制)
- [常見問題與除錯 (FAQ)](#常見問題與除錯-faq)

---

## 環境前置設定

### 為 ec_bridge_server.py 設定免密碼 sudo
由於 `cros_sdk` 與 `flash_ec` 執行時可能需要 sudo 權限，為避免伺服器在背景執行時因等待密碼輸入而卡住，請在宿主機進行以下設定：

```bash
# 編輯 sudoers 設定檔
sudo visudo -f /etc/sudoers.d/cros_sdk_nopasswd
```
-> 輸入以下內容：
```text
yuan ALL=(ALL:ALL) NOPASSWD: ALL
```
-> 存檔後關閉

---

## 系統架構與預設路徑

本服務預設監聽於 `0.0.0.0:8000`，同時提供 REST API 與 MCP 雙介面，並操作宿主機上的以下目錄：

| 變數名稱 | 預設路徑 | 說明 |
| :--- | :--- | :--- |
| `CHROMIUMOS_DIR` | `~/chromiumos` | ChromiumOS 原始碼根目錄（執行 `cros_sdk` 的工作目錄） |
| `EC_DIR` | `~/chromiumos/src/platform/ec` | Chrome-EC 韌體專案目錄（執行 `git` / `repo sync` 的工作目錄） |

FastAPI 自動生成的互動式文件：
- **Swagger UI**: `http://host.docker.internal:8000/docs`（或從宿主機瀏覽器開啟 `http://localhost:8000/docs`）
- **ReDoc**: `http://host.docker.internal:8000/redoc`
- **MCP 端點**: `http://host.docker.internal:8000/mcp`（詳見 [Hermes MCP 整合指南](hermes_mcp_integration_guide.md)）

---

## 伺服器啟動方式

### 方法一：使用腳本啟動（推薦）
```bash
./run.sh
```

### 方法二：手動啟動虛擬環境
```bash
source venv/bin/activate
python ec_bridge_server.py
```
---

## Docker 容器連線設定 (host.docker.internal)

當您的客戶端程式或 AI Agent 運行在 **Docker 容器** 內部時，請透過 `http://host.docker.internal:8000` 連線至宿主機。

### Docker 容器啟動參數配置
啟動 Docker 容器時，需加上 `--add-host=host.docker.internal:host-gateway` 確保容器內能正確解析宿主機 IP：

```bash
# docker run 啟動範例
docker run -it --add-host=host.docker.internal:host-gateway <IMAGE_NAME> bash
```

若使用 `docker-compose.yml`：
```yaml
services:
  agent:
    image: <IMAGE_NAME>
    extra_hosts:
      - "host.docker.internal:host-gateway"
```

---

## 共用資料結構 (Data Models)

### 標準指令回應格式 (`CommandResponse`)
所有執行系統指令的 API 端點（Build、Repo Sync、Git、Flash、DutControl）皆回傳統一格式：

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

| 欄位 | 型態 | 說明 |
| :--- | :--- | :--- |
| `success` | `bool` | 指令是否執行成功 (`return_code == 0`) |
| `return_code` | `int` | 子行程回傳碼（若超時回傳 `-1`） |
| `command` | `string` | 伺服器實際執行的完整指令字串 |
| `stdout` | `string` | 指令標準輸出 |
| `stderr` | `string` | 指令標準錯誤輸出 |
| `error_summary` | `string` 或 `null` | 錯誤摘要。若編譯失敗，會自動擷取最後 20 行關鍵錯誤訊息 |

---

## API 端點詳細清單

### 1. 查詢可用 API 清單 (GET /api/v1/endpoints) - Agent 專用

* **說明**：專為 AI Agent 在開始 Debug 任務時設計。快速回傳所有可用端點名稱、HTTP 方法、簡短描述與 Request Body 參數格式。**格式極度精簡，最大化節省 LLM Context Window Token**。
* **HTTP 方法**：`GET`
* **路徑**：`/api/v1/endpoints`（別名：`/api/v1/list`）
* **請求參數**：無

#### Docker 內呼叫指令 (cURL)
```bash
curl -X GET http://host.docker.internal:8000/api/v1/endpoints
```

#### 回應範例 (`200 OK` - 極簡 Token 格式)
```json
{
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
        "subcommand*": ["branch", "diff", "log", "show", "status"],
        "args": "list[str] (default=[])",
        "timeout_seconds": "int (default=30)"
      }
    },
    {
      "method": "POST",
      "path": "/api/v1/repo/sync",
      "desc": "Sync EC repo (repo sync . in src/platform/ec)",
      "body": null
    },
    {
      "method": "GET",
      "path": "/health",
      "desc": "Health check & workspace dirs",
      "body": null
    },
    {
      "method": "GET",
      "path": "/api/v1/endpoints",
      "desc": "List all endpoints (compact schema for LLM/Agent)",
      "body": null
    }
  ]
}
```

---

### 2. 伺服器健康檢查 (GET /health)

* **說明**：確認 Bridge 伺服器運行狀態及 ChromiumOS 與 EC 目錄配置。
* **HTTP 方法**：`GET`
* **路徑**：`/health`
* **請求參數**：無

#### Docker 內呼叫指令 (cURL)
```bash
curl -X GET http://host.docker.internal:8000/health
```

#### 回應範例 (`200 OK`)
```json
{
  "status": "ok",
  "chromiumos_dir": "/home/yuan/chromiumos",
  "ec_dir": "/home/yuan/chromiumos/src/platform/ec"
}
```

---

### 3. EC 韌體編譯 (POST /api/v1/build/ec)

* **說明**：在 `CHROMIUMOS_DIR` 目錄下調用 `cros_sdk -- zmake build <project> [--clobber]` 進行韌體編譯。若編譯失敗，自動分析並擷取 `error_summary`。
* **HTTP 方法**：`POST`
* **路徑**：`/api/v1/build/ec`
* **底層執行指令**：`cros_sdk -- zmake build <project> [--clobber]`

#### 請求主體 (`BuildRequest`)
| 欄位 | 型態 | 必填 | 預設值 | 說明 |
| :--- | :--- | :--- | :--- | :--- |
| `project` | `string` | **是** | - | EC Project 名稱（只允許英數字、底線、減號，例如 `bluey`、`matsu`） |
| `clobber` | `bool` | 否 | `true` | 是否加入 `--clobber` 進行全清理乾淨編譯 |
| `timeout_seconds` | `int` | 否 | `600` | 編譯超時上限（秒） |

#### Docker 內呼叫指令 (cURL)

**基本範例（全清理重建 bluey 專案）：**
```bash
curl -X POST http://host.docker.internal:8000/api/v1/build/ec \
     -H "Content-Type: application/json" \
     -d '{
       "project": "bluey",
       "clobber": true,
       "timeout_seconds": 600
     }'
```

**增量編譯範例（不清理，加速編譯）：**
```bash
curl -X POST http://host.docker.internal:8000/api/v1/build/ec \
     -H "Content-Type: application/json" \
     -d '{
       "project": "bluey",
       "clobber": false,
       "timeout_seconds": 300
     }'
```

#### 成功回應範例 (`200 OK`)
```json
{
  "success": true,
  "return_code": 0,
  "command": "cros_sdk -- zmake build bluey --clobber",
  "stdout": "Building bluey...\nTarget: zephyr.bin generated.\nBUILD SUCCESSFUL",
  "stderr": "",
  "error_summary": null
}
```

#### 失敗回應範例 (`200 OK`, `success: false`)
```json
{
  "success": false,
  "return_code": 1,
  "command": "cros_sdk -- zmake build bluey --clobber",
  "stdout": "...",
  "stderr": "src/platform/ec/board/bluey/board.c:45:10: error: 'UNDEFINED_MACRO' undeclared here\nFAILED: build.ninja",
  "error_summary": "src/platform/ec/board/bluey/board.c:45:10: error: 'UNDEFINED_MACRO' undeclared here\nFAILED: build.ninja"
}
```

---

### 4. 切換與下載指定 EC CL (POST /api/v1/repo/checkout)

* **說明**：在 `CHROMIUMOS_DIR` (`~/chromiumos`) 目錄下執行 `repo download chromiumos/platform/ec <cl_number>` 下載並切換至指定的 EC Gerrit Change List (CL)。
* **HTTP 方法**：`POST`
* **路徑**：`/api/v1/repo/checkout`（別名：`/api/v1/repo/download`）
* **底層執行指令**：`repo download chromiumos/platform/ec <cl_number>` (在 `~/chromiumos` 執行)

#### 請求主體 (`RepoCheckoutRequest`)
| 欄位 | 型態 | 必填 | 預設值 | 說明 |
| :--- | :--- | :--- | :--- | :--- |
| `cl_number` | `string` | **是** | - | EC CL 編號，例如 `"8231407"` 或 `"8231407/1"`（純數字或帶 patchset） |
| `timeout_seconds` | `int` | 否 | `300` | 執行超時上限（秒） |

#### Docker 內呼叫指令 (cURL)
以下範例checkout到 https://chromium-review.googlesource.com/c/chromiumos/platform/ec/+/8231407
```bash
curl -X POST http://host.docker.internal:8000/api/v1/repo/checkout \
     -H "Content-Type: application/json" \
     -d '{"cl_number": "8231407"}'
```

#### 回應範例 (`200 OK`)
```json
{
  "success": true,
  "return_code": 0,
  "command": "repo download chromiumos/platform/ec 8231407",
  "stdout": "Downloading 8231407 ...\nSwitched to branch change-8231407",
  "stderr": "",
  "error_summary": null
}
```

---

### 5. 同步 EC 程式庫 (POST /api/v1/repo/sync)

* **說明**：在 `EC_DIR` (`~/chromiumos/src/platform/ec`) 目錄下執行 `repo sync .` 同步當前 EC 專案程式庫。
* **HTTP 方法**：`POST`
* **路徑**：`/api/v1/repo/sync`
* **底層執行指令**：`repo sync .` (預設超時 600 秒)
* **請求主體**：無 (Empty Body)

#### Docker 內呼叫指令 (cURL)
```bash
curl -X POST http://host.docker.internal:8000/api/v1/repo/sync
```

#### 回應範例 (`200 OK`)
```json
{
  "success": true,
  "return_code": 0,
  "command": "repo sync .",
  "stdout": "Fetching project src/platform/ec\nUpdating files: 100% (2345/2345), done.",
  "stderr": "",
  "error_summary": null
}
```

---

### 6. 執行 Git 查詢指令 (POST /api/v1/git/command)

* **說明**：在 `EC_DIR` (`~/chromiumos/src/platform/ec`) 目錄下執行經白名單許可的安全 Git 指令。
* **HTTP 方法**：`POST`
* **路徑**：`/api/v1/git/command`
* **底層執行指令**：`git <subcommand> [args...]`
* **允許的子指令白名單**：`status`, `diff`, `log`, `show`, `branch`

#### 請求主體 (`GitRequest`)
| 欄位 | 型態 | 必填 | 預設值 | 說明 |
| :--- | :--- | :--- | :--- | :--- |
| `subcommand` | `string` | **是** | - | Git 子指令（必須在白名單內） |
| `args` | `List[string]` | 否 | `[]` | 額外參數列表，例如 `["--stat"]`, `["-n", "5"]`, `["HEAD~1"]` |
| `timeout_seconds` | `int` | 否 | `30` | 執行超時上限（秒） |

#### Docker 內呼叫指令範例 (cURL)

**範例 A：查詢 Git 狀態 (`git status -s`)**
```bash
curl -X POST http://host.docker.internal:8000/api/v1/git/command \
     -H "Content-Type: application/json" \
     -d '{
       "subcommand": "status",
       "args": ["-s"],
       "timeout_seconds": 30
     }'
```

**範例 B：檢視最近一次 Commit 的 Diff (`git diff HEAD~1`)**
```bash
curl -X POST http://host.docker.internal:8000/api/v1/git/command \
     -H "Content-Type: application/json" \
     -d '{
       "subcommand": "diff",
       "args": ["HEAD~1"],
       "timeout_seconds": 30
     }'
```

**範例 C：查詢最近 3 筆 Commit 紀錄 (`git log -n 3 --oneline`)**
```bash
curl -X POST http://host.docker.internal:8000/api/v1/git/command \
     -H "Content-Type: application/json" \
     -d '{
       "subcommand": "log",
       "args": ["-n", "3", "--oneline"],
       "timeout_seconds": 30
     }'
```

**範例 D：檢視分支列表 (`git branch -a`)**
```bash
curl -X POST http://host.docker.internal:8000/api/v1/git/command \
     -H "Content-Type: application/json" \
     -d '{
       "subcommand": "branch",
       "args": ["-a"],
       "timeout_seconds": 30
     }'
```

#### 違規指令回應範例 (`403 Forbidden`)
若嘗試執行非白名單指令（如 `push`, `reset`, `checkout`, `clean` 等）：
```json
{
  "detail": "禁止執行該 Git 指令: reset。目前僅允許: {'branch', 'status', 'show', 'diff', 'log'}"
}
```

---

### 7. EC 韌體燒錄 (POST /api/v1/flash/ec)

* **說明**：在 `CHROMIUMOS_DIR` 目錄下調用 `cros_sdk -- flash_ec --board=<board>` 將編譯好的韌體燒錄至實體開發板或測試裝置。
* **HTTP 方法**：`POST`
* **路徑**：`/api/v1/flash/ec`
* **底層執行指令**：`cros_sdk -- flash_ec --board=<board>`

#### 請求主體 (`FlashRequest`)
| 欄位 | 型態 | 必填 | 預設值 | 說明 |
| :--- | :--- | :--- | :--- | :--- |
| `board` | `string` | 否 | `"matsu"` | 要燒錄的硬體板名稱（只允許英數字、底線、減號） |
| `timeout_seconds` | `int` | 否 | `300` | 燒錄超時上限（秒） |

#### Docker 內呼叫指令 (cURL)

**燒錄指定板子 (例如 bluey)：**
```bash
curl -X POST http://host.docker.internal:8000/api/v1/flash/ec \
     -H "Content-Type: application/json" \
     -d '{"board": "bluey"}'
```

**自訂超時上限燒錄 (例如 matsu, 300 秒)：**
```bash
curl -X POST http://host.docker.internal:8000/api/v1/flash/ec \
     -H "Content-Type: application/json" \
     -d '{
       "board": "matsu",
       "timeout_seconds": 300
     }'
```

#### 回應範例 (`200 OK`)
```json
{
  "success": true,
  "return_code": 0,
  "command": "cros_sdk -- flash_ec --board=bluey",
  "stdout": "Flashing board bluey via servo...\nImage successfully flashed.",
  "stderr": "",
  "error_summary": null
}
```

---

### 8. Servo / DUT 控制 (POST /api/v1/servo/dut-control)

* **說明**：在宿主機直接執行 Servo 開發除錯控制指令 (`dut-control`)。支援電源控制、韌體防寫保護、UART 終端 Port 查詢、EC Console 指令發送與 USB 隨身碟指向切換。
* **HTTP 方法**：`POST`
* **路徑**：`/api/v1/servo/dut-control`（別名：`/api/v1/dut-control`）
* **底層執行指令**：`dut-control [-p <port>] -- <controls...>`（直接於宿主機執行，不透過 cros_sdk，並自動在 controls 前加上 `--` 參數）

#### 請求主體 (`DutControlRequest`)
| 欄位 | 型態 | 必填 | 預設值 | 說明 |
| :--- | :--- | :--- | :--- | :--- |
| `controls` | `List[string]` | **是** | - | 一或多個 `dut-control` 控制項或查詢名稱（指令會自動附加於 `--` 之後） |
| `port` | `int` | 否 | `null` | Servod 連線 Port（若未指定則使用預設埠 9999） |
| `timeout_seconds` | `int` | 否 | `30` | 執行超時上限（秒） |

#### 常用指令支援清單與 Docker 內呼叫範例 (cURL)

**1. 設定 ServoV4 PD 供電角色為 SNK (斷開 DUT 供電 - DUT no power)：**
```bash
curl -X POST http://host.docker.internal:8000/api/v1/servo/dut-control \
     -H "Content-Type: application/json" \
     -d '{"controls": ["servo_v4_role:snk"]}'
```

**2. 設定 ServoV4 PD 供電角色為 SRC (對 DUT 供電 - supply DUT power)：**
```bash
curl -X POST http://host.docker.internal:8000/api/v1/servo/dut-control \
     -H "Content-Type: application/json" \
     -d '{"controls": ["servo_v4_role:src"]}'
```

**3. 進入 Recovery 模式 (System to recovery mode)：**
```bash
curl -X POST http://host.docker.internal:8000/api/v1/servo/dut-control \
     -H "Content-Type: application/json" \
     -d '{"controls": ["power_state:rec"]}'
```

**4. 啟用 EC/BIOS 寫入保護 (Enable EC/BIOS Write Protection)：**
```bash
curl -X POST http://host.docker.internal:8000/api/v1/servo/dut-control \
     -H "Content-Type: application/json" \
     -d '{"controls": ["fw_wp_state:force_on"]}'
```

**5. 停用 EC/BIOS 寫入保護 (Disable EC/BIOS Write Protection)：**
```bash
curl -X POST http://host.docker.internal:8000/api/v1/servo/dut-control \
     -H "Content-Type: application/json" \
     -d '{"controls": ["fw_wp_state:force_off"]}'
```

**6. 查詢 EC UART 終端 Port (Get EC uart port)：**
```bash
curl -X POST http://host.docker.internal:8000/api/v1/servo/dut-control \
     -H "Content-Type: application/json" \
     -d '{"controls": ["ec_uart_pty"]}'
```

**7. 查詢 BIOS/CPU UART 終端 Port (Get BIOS uart port)：**
```bash
curl -X POST http://host.docker.internal:8000/api/v1/servo/dut-control \
     -H "Content-Type: application/json" \
     -d '{"controls": ["cpu_uart_pty"]}'
```

**8. 查詢 Cr50/GSC UART 終端 Port (Get Cr50 uart port)：**
```bash
curl -X POST http://host.docker.internal:8000/api/v1/servo/dut-control \
     -H "Content-Type: application/json" \
     -d '{"controls": ["cr50_uart_pty"]}'
```

**9. 查詢 ServoV4 USB-PD 供電資訊 (Print servoV4 usb-pd power info)：**
```bash
curl -X POST http://host.docker.internal:8000/api/v1/servo/dut-control \
     -H "Content-Type: application/json" \
     -d '{"controls": ["ada_srccaps"]}'
```

**10. 發送 Console 指令至 EC (Send console command 'version' to EC console)：**
```bash
curl -X POST http://host.docker.internal:8000/api/v1/servo/dut-control \
     -H "Content-Type: application/json" \
     -d '{"controls": ["ec_uart_cmd:version"]}'
```

**11. 切換 USB 隨身碟指向 (USB-key direction to DUT / Servo)：**
```bash
# 指向 DUT
curl -X POST http://host.docker.internal:8000/api/v1/servo/dut-control \
     -H "Content-Type: application/json" \
     -d '{"controls": ["image_usbkey_direction:dut_sees_usbkey"]}'

# 指向 Servo
curl -X POST http://host.docker.internal:8000/api/v1/servo/dut-control \
     -H "Content-Type: application/json" \
     -d '{"controls": ["image_usbkey_direction:servo_sees_usbkey"]}'
```

**12. 批次查詢範例（一次查詢多個控制項）：**
```bash
curl -X POST http://host.docker.internal:8000/api/v1/servo/dut-control \
     -H "Content-Type: application/json" \
     -d '{
       "controls": [
         "ec_uart_pty",
         "cpu_uart_pty",
         "cr50_uart_pty",
         "servo_v4_role"
       ],
       "timeout_seconds": 30
     }'
```

#### 回應範例 (`200 OK`)
```json
{
  "success": true,
  "return_code": 0,
  "command": "dut-control -- ec_uart_pty cpu_uart_pty",
  "stdout": "ec_uart_pty:/dev/pts/12\ncpu_uart_pty:/dev/pts/13",
  "stderr": "",
  "error_summary": null
}
```

---

## Docker 內 Python 呼叫範例代碼

若您的 Agent 使用 Python 開發，可參考以下用戶端封裝範例 (`ec_client.py`)：

```python
import requests
from typing import Optional, List, Dict, Any

class ECBridgeClient:
    def __init__(self, base_url: str = "http://host.docker.internal:8000"):
        self.base_url = base_url

    def list_endpoints(self) -> Dict[str, Any]:
        """查詢可用 API 清單 (精簡 Token 格式)"""
        resp = requests.get(f"{self.base_url}/api/v1/endpoints", timeout=5)
        resp.raise_for_status()
        return resp.json()

    def check_health(self) -> Dict[str, Any]:
        """健康檢查"""
        resp = requests.get(f"{self.base_url}/health", timeout=5)
        resp.raise_for_status()
        return resp.json()

    def build_ec(self, project: str, clobber: bool = True, timeout: int = 600) -> Dict[str, Any]:
        """觸發 EC 編譯"""
        payload = {
            "project": project,
            "clobber": clobber,
            "timeout_seconds": timeout
        }
        resp = requests.post(f"{self.base_url}/api/v1/build/ec", json=payload, timeout=timeout + 5)
        resp.raise_for_status()
        return resp.json()

    def git_command(self, subcommand: str, args: Optional[List[str]] = None, timeout: int = 30) -> Dict[str, Any]:
        """執行白名單 Git 指令"""
        payload = {
            "subcommand": subcommand,
            "args": args or [],
            "timeout_seconds": timeout
        }
        resp = requests.post(f"{self.base_url}/api/v1/git/command", json=payload, timeout=timeout + 5)
        resp.raise_for_status()
        return resp.json()

    def repo_checkout(self, cl_number: str, timeout: int = 300) -> Dict[str, Any]:
        """下載並切換至指定的 EC CL"""
        payload = {
            "cl_number": str(cl_number),
            "timeout_seconds": timeout
        }
        resp = requests.post(f"{self.base_url}/api/v1/repo/checkout", json=payload, timeout=timeout + 5)
        resp.raise_for_status()
        return resp.json()

    def repo_sync(self, timeout: int = 600) -> Dict[str, Any]:
        """同步 EC 程式碼"""
        resp = requests.post(f"{self.base_url}/api/v1/repo/sync", timeout=timeout + 5)
        resp.raise_for_status()
        return resp.json()

    def flash_ec(self, board: str = "bluey", timeout: int = 300) -> Dict[str, Any]:
        """燒錄 EC 韌體"""
        payload = {
            "board": board,
            "timeout_seconds": timeout
        }
        resp = requests.post(f"{self.base_url}/api/v1/flash/ec", json=payload, timeout=timeout + 5)
        resp.raise_for_status()
        return resp.json()

    def dut_control(self, controls: List[str], port: Optional[int] = None, timeout: int = 30) -> Dict[str, Any]:
        """執行 dut-control 指令"""
        payload = {
            "controls": controls,
            "port": port,
            "timeout_seconds": timeout
        }
        resp = requests.post(f"{self.base_url}/api/v1/servo/dut-control", json=payload, timeout=timeout + 5)
        resp.raise_for_status()
        return resp.json()

# 使用示範
if __name__ == "__main__":
    client = ECBridgeClient()

    # 1. Debug 任務啟動前：先查詢所有可用 API
    print("Available APIs:", client.list_endpoints())

    # 2. 檢查連線
    print("Health:", client.check_health())

    # 3. 下載並切換至特定 CL (例如 8231407)
    checkout_res = client.repo_checkout(cl_number="8231407")
    print("Repo Checkout Output:\n", checkout_res["stdout"])

    # 4. 查詢 UART 終端 Port
    uart_res = client.dut_control(["ec_uart_pty", "cpu_uart_pty", "cr50_uart_pty"])
    print("UART Ports:\n", uart_res["stdout"])

    # 5. 控制 DUT 供電與 Recovery 模式
    client.dut_control(["servo_v4_role:src"])
    client.dut_control(["power_state:rec"])

    # 6. 發送 Console 指令至 EC
    ec_ver = client.dut_control(["ec_uart_cmd:version"])
    print("EC Version Output:\n", ec_ver["stdout"])

    # 7. 編譯並燒錄 bluey
    print("Building bluey...")
    build_res = client.build_ec(project="bluey", clobber=False)
    if build_res["success"]:
        print("Build success, flashing...")
        flash_res = client.flash_ec(board="bluey")
        print("Flash result:", flash_res["stdout"])
```

---

## MCP (Model Context Protocol) 介面

自 v1.3.0 起，Bridge Server 同時提供 **MCP 介面**，讓支援 MCP 的 AI Agent 能以標準化協議自動發現並呼叫所有工具，無需手動撰寫 HTTP Client。

### MCP 端點

| 項目 | 值 |
| :--- | :--- |
| MCP URL (Docker 內) | `http://host.docker.internal:8000/mcp` |
| MCP URL (宿主機本地) | `http://localhost:8000/mcp` |
| 傳輸方式 | Streamable HTTP |
| 支援 Tools 數量 | 8 個（與 REST API 完全對應） |

### REST API vs MCP 對照

| REST API | MCP Tool |
| :--- | :--- |
| `GET /health` | `health_check` |
| `GET /api/v1/endpoints` | `list_endpoints` |
| `POST /api/v1/build/ec` | `build_ec` |
| `POST /api/v1/repo/checkout` | `repo_checkout` |
| `POST /api/v1/repo/sync` | `repo_sync` |
| `POST /api/v1/git/command` | `git_command` |
| `POST /api/v1/flash/ec` | `flash_ec` |
| `POST /api/v1/servo/dut-control` | `dut_control` |

### Hermes Agent 快速設定

在 Hermes Agent 的 MCP 設定檔中加入：

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

> 📖 **完整 MCP 整合指南（含 Python Client 範例、Docker 設定、所有 Tool 參數說明）請參閱：[hermes_mcp_integration_guide.md](hermes_mcp_integration_guide.md)**

---

## 安全性與 Git 白名單機制

為確保外部呼叫者或自動化 AI Agent 不會對主機環境造成非預期的破壞，本伺服器實施以下安全限制：

1. **參數格式驗證 (Regex Validation)**
   - `project` 與 `board` 參數均經正規表達式 `^[a-zA-Z0-9_\-]+$` 校驗，防止 Command Injection 攻擊。
   - `cl_number` 參數經 `^[0-9]+(/[0-9]+)?$` 校驗。
2. **Git 指令白名單限制**
   - 僅允許讀取與查詢類的 Git 子指令：`{"status", "diff", "log", "show", "branch"}`。
   - 禁止任何寫入、重置或破壞性指令（如 `git reset --hard`, `git push`, `git checkout`, `git clean` 等）。
3. **執行超時保護 (Timeout Handling)**
   - 每個端點均設有最大超時保護機制，避免子行程掛起（Hang）耗盡系統資源。

---

## 常見問題與除錯 (FAQ)

### Q1: 在 Docker 內執行 cURL 出現 `Connection refused` (連線被拒絕)
* **原因**：容器內未正確解析宿主機或 server 未監聽 `0.0.0.0`。
* **解法**：
  1. 啟動 Docker 容器時務必加入 `--add-host=host.docker.internal:host-gateway`。
  2. 確認宿主機的 `ec_bridge_server.py` 是否正常啟動於 `0.0.0.0:8000`。

### Q2: 呼叫 API 出現 `500 Internal Server Error: 目錄不存在`
* **原因**：宿主機上的 `~/chromiumos` 或 `~/chromiumos/src/platform/ec` 路徑不存在或權限不足。
* **解法**：確認執行伺服器的使用者帳號家目錄下是否已正確 checkout ChromiumOS 專案。

### Q3: 編譯超時 (`TimeoutExpired`) 回傳 `return_code: -1`
* **原因**：初次全編譯 (`clobber: true`) 或 repo sync 耗時超過預設上限。
* **解法**：在請求 JSON 中調大 `timeout_seconds`（例如 `1200` 代表 20 分鐘）。
