# Chrome-EC-Hermes-Bridge

將 Chrome EC 開發環境透過 MCP 提供給 Docker 內的 Hermes Agent。讓 Hermes 無須取得主機（Host）的完整存取權限即可進行開發，並能透過 MCP 安全地調用如 `cros_sdk`、`zmake`、`git`、`repo`、`flash_ec` 與 `dut-control` 等 Host 端的 EC 開發工具。

## 1. Host 安裝與啟動

### Clone Repository

```bash
git clone https://github.com/yuansco/Chrome-EC-Hermes-Bridge.git
cd Chrome-EC-Hermes-Bridge
```

確保 Host 已經準備好：

* Python 3
* `~/chromiumos` ChromiumOS source tree
* `cros_sdk`
* Servod / dut-control 開發環境

### 啟動 Bridge

直接執行：

```bash
./run.sh
```

`run.sh` 會自動：

1. 建立 Python `venv`
2. 啟用 virtual environment
3. 檢查必要套件
4. 依 `requirements.txt` 自動安裝缺少的套件
5. 啟動 EC Bridge Server

啟動成功後：

```text
REST API : http://0.0.0.0:8000/api/v1/
Swagger  : http://0.0.0.0:8000/docs
MCP      : http://0.0.0.0:8000/mcp
```

保持這個 Host terminal 持續執行。
可以在 `http://0.0.0.0:8000/docs` 測試 Server 是否可以操作 cros_sdk

## 2. Docker 內 Hermes Agent 設定 MCP

Docker 內的 Hermes Agent 透過 `host.docker.internal` 連接 Host：

```text
Hermes Agent (Docker)
        │
        │ MCP / HTTP
        ▼
host.docker.internal:8000
        │
        ▼
Chrome-EC-Hermes-Bridge (Host)
        │
        ▼
cros_sdk / dut-control / repo / git
```

Docker 必須能解析 Host：

```bash
--add-host=host.docker.internal:host-gateway
```

### Hermes MCP 設定

在 Hermes 的 `config.yaml` 加入：

```yaml
mcp_servers:
  chrome-ec-bridge:
    url: http://host.docker.internal:8000/mcp/sse
    transport: sse
    headers:
      Host: localhost:8000
```

重新啟動 Hermes：

```text
docker restart hermes
```

使用`mcp list`確認 MCP tools 已經載入：
```shell
yuan@yuan-Caboc:~$ docker exec -it hermes hermes mcp list

  MCP Servers:

  Name             Transport                      Tools        Status    
  ──────────────── ────────────────────────────── ──────────── ──────────
  chrome-ec-bridge http://host.docker.intern...   all          ✓ enabled

yuan@yuan-Caboc:~$
```
Hermes 會自動從 MCP Server discovery 可用的 tools。


## 3. Hermes Skill 設定

在 Hermes 的 skills 建立 EC 開發專用 Skill 目錄，將 `SKILL.md` 與 `scripts/mcp_call.py` 複製到資料夾，例如：

```text
~/.hermes/skills/chrome-ec-develop/
├── SKILL.md
└── scripts/
    └── mcp_call.py
```

安裝 / 載入 Skill 後，重新啟動 Hermes，讓 Skill 與 MCP tools 一起載入。

## 4. Quick Start

完成後所有設定後即可透過與 Hermes Agent 對話操作 Host 端的 Chrome EC 開發環境。

