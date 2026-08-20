#!/usr/bin/env bash
set -e

# 定位腳本所在目錄
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

VENV_DIR="$SCRIPT_DIR/venv"
REQUIREMENTS_FILE="$SCRIPT_DIR/requirements.txt"
REQUIRED_PKGS=("fastapi" "uvicorn" "pydantic")

echo "=========================================="
echo "  Chrome-EC Hermes Bridge Server Startup  "
echo "=========================================="

# 1. 檢查並建立虛擬環境 (venv)
if [ ! -d "$VENV_DIR" ] || [ ! -f "$VENV_DIR/bin/activate" ]; then
    echo "[INFO] 虛擬環境 (venv) 不存在，正在建立..."
    python3 -m venv "$VENV_DIR"
    echo "[INFO] 虛擬環境建立完成。"
fi

# 2. 啟動虛擬環境
source "$VENV_DIR/bin/activate"

# 3. 檢查套件是否缺失
MISSING_PKGS=()
for pkg in "${REQUIRED_PKGS[@]}"; do
    if ! python -c "import $pkg" 2>/dev/null; then
        MISSING_PKGS+=("$pkg")
    fi
done

# 4. 若有套件缺失，自動執行安裝
if [ ${#MISSING_PKGS[@]} -ne 0 ]; then
    echo "[WARN] 偵測到缺失套件: ${MISSING_PKGS[*]}"
    echo "[INFO] 正在自動安裝必要套件..."
    
    # 確保 pip 保持在最新版
    pip install --upgrade pip -q 2>/dev/null || true
    
    if [ -f "$REQUIREMENTS_FILE" ]; then
        echo "[INFO] 依據 requirements.txt 進行安裝..."
        pip install -r "$REQUIREMENTS_FILE"
    else
        echo "[INFO] 直接安裝指定套件: ${REQUIRED_PKGS[*]}..."
        pip install "${REQUIRED_PKGS[@]}"
    fi
    echo "[INFO] 套件安裝完成！"
else
    echo "[OK] 所有必要 Python 套件已備齊 (${REQUIRED_PKGS[*]})."
fi

# 5. 檢查伺服器主程式檔案
TARGET_SERVER="ec_bridge_server.py"
if [ ! -f "$SCRIPT_DIR/$TARGET_SERVER" ]; then
    if [ -f "$SCRIPT_DIR/ec_build_server.py" ]; then
        TARGET_SERVER="ec_build_server.py"
    else
        echo "[ERROR] 找不到伺服器主程式 (ec_bridge_server.py 或 ec_build_server.py)"
        exit 1
    fi
fi

# 6. 啟動伺服器
echo "[INFO] 正在啟動伺服器: $TARGET_SERVER (監聽 http://0.0.0.0:8000)..."
exec python "$SCRIPT_DIR/$TARGET_SERVER" "$@"
