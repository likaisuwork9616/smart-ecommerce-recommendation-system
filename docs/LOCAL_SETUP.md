# 本機環境與操作方式

此環境建置於 `E:\kai_work\shop`，供 Olist 資料匯入、SQL、EDA 與 Stage 4 模型實驗使用。

## 已安裝的環境

| 項目 | 版本／位置 |
| --- | --- |
| Python | 既有 Python 3.12.10，專案虛擬環境 `.venv/` |
| Visual C++ x64 Runtime | 既有 14.40.33816，已確認符合 MySQL 執行需求 |
| pandas | 3.0.6 |
| Matplotlib | 3.11.2 |
| SQLAlchemy／PyMySQL | 2.1.4／1.2.3 |
| cryptography | 50.0.2 |
| scikit-learn／joblib | 1.9.1／1.6.0，Stage 4 訓練與模型保存 |
| XGBoost／LightGBM | 3.4.1／4.7.0，Stage 4 多模型時間回測 |
| JupyterLab／Notebook | 4.6.4／7.6.3 |
| Jupyter kernel | `.venv`，顯示名稱 `Shop (Python 3.12)` |
| MySQL Community | 8.4.11，`.runtime/tools/mysql-8.4.11-winx64/` |
| DBeaver Community | 26.2.2，`.runtime/tools/dbeaver/`，內含 Java |
| MySQL Connector/J | 26.7.0，DBeaver 已設定使用本機 JAR |
| Olist 原始資料 | `data/raw/olist/`，9 個官方 CSV |

MySQL ZIP 已比對官方 MD5；DBeaver ZIP 已比對官方 SHA-256。下載檔保存在 `.runtime/downloads/`。這些工具沒有註冊 Windows 開機服務。

Python 套件（包含 XGBoost、LightGBM）都安裝在 `.venv/`。MySQL 是獨立程式與服務，程式、資料與設定放在 `.runtime/`，不屬於 Python 虛擬環境。重新建立 Python 環境可使用 `requirements-lock.txt`；該鎖定清單對應目前的 Windows x64／Python 3.12。

2026-10-12 已實測通過：套件相依性檢查、9 張資料表筆數檢查、三本 Notebook 完整執行，並重新產出 8 張 EDA 圖表。MySQL 停止／重啟與 JupyterLab HTTP API、kernel、Notebook 根目錄也已通過檢查。驗證摘要保存在 `.runtime/verification/summary.json` 與 `jupyter-server.json`。

Stage 4 更新亦已驗證：21 次多模型時間回測訓練成功、19 項自動測試通過，`04_olist_delay_prediction.ipynb` 的 11 個程式區塊完整執行。Notebook 執行副本與摘要保存在 `.runtime/verification/`，GitHub 保留未執行的教學原檔。

## 開始分析

在專案根目錄的 PowerShell 執行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_jupyter.ps1
```

這個指令會先啟動本專案的 MySQL，再開啟 JupyterLab。Notebook 工作目錄設為 `notebooks/`，符合前三本 Notebook 使用 `Path.cwd().parent` 的寫法。請選擇 `Shop (Python 3.12)` kernel，依序開啟 `01`、`02`、`03`、`04`。

Jupyter 使用 `127.0.0.1:8888`，保留預設登入 token；若瀏覽器未自動開啟，可使用終端顯示的完整網址。按 `Ctrl+C` 關閉 Jupyter 後，MySQL 仍會執行。

需要單獨啟停資料庫時：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_mysql.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\stop_mysql.ps1
```

## DBeaver

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_dbeaver.ps1
```

啟動腳本使用專案內的 workspace，DBeaver 全域設定也導向 `.runtime/DBeaverData`。已預建 `Olist local (127.0.0.1:3307)` 連線，並配置經官方 SHA-256 校驗的本機 JDBC driver。第一次連線時，請從 `scripts/db_config.py` 讀取密碼並輸入。DBeaver 的程式、Java 與設定檔已檢查；圖形介面的載入與操作仍待首次開啟確認。

連線設定如下：

| 欄位 | 值 |
| --- | --- |
| Driver | MySQL |
| Host | `127.0.0.1` |
| Port | `3307` |
| Database | `olist_ecommerce` |
| Username | `olist_app` |
| Password | 讀取本機 `scripts/db_config.py` 的 `password` 欄位 |

資料庫只監聽本機。應用程式帳號的權限限制在 `olist_ecommerce`；帳密由亂數產生，保存在 Git 忽略的 `scripts/db_config.py`。管理員設定保存在 `.runtime/mysql/admin.ini`，供停止資料庫使用。

## 驗證與重新匯入

檢查 Python、套件、MySQL 與 9 張表筆數：

```powershell
.\.venv\Scripts\python.exe scripts\verify_environment.py
```

額外重新執行三本 Notebook：

```powershell
.\.venv\Scripts\python.exe scripts\verify_environment.py --execute-notebooks
```

報告、執行副本與新圖表存入 `.runtime/verification/`；驗證不覆寫 Git 追蹤的 Notebook 與原圖表。

原始 CSV 的匯入指令如下。現有匯入程式使用 `if_exists="replace"`，會重建同名資料表；只有確定要重新匯入時才執行：

```powershell
.\.venv\Scripts\python.exe scripts\load_olist_to_mysql.py
```

## 在另一台電腦重建

1. 安裝 Python 3.12，執行 `py -3.12 -m venv .venv`。
   Windows 也必須具備 [Microsoft Visual C++ x64 Redistributable](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist)，這是 MySQL 8.4 的必要 runtime。
2. 執行 `.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt`。鎖定清單對應 Windows x64／Python 3.12；一般需求清單為 `requirements.txt`。
3. 從官方來源下載 MySQL 8.4.11 Windows x64 ZIP，解壓至 `.runtime/tools/`，保留 `mysql-8.4.11-winx64` 目錄名。
4. 執行 `.\.venv\Scripts\python.exe scripts\setup_local_mysql.py`。這只用於全新環境，偵測到既有資料或連線設定就會停止，避免覆寫。
5. 從 Olist 官方 Kaggle 頁下載資料，將 9 個 CSV 放入 `data/raw/olist/`，再執行匯入指令。
6. 執行 `.\.venv\Scripts\python.exe -m ipykernel install --sys-prefix --name .venv --display-name "Shop (Python 3.12)"`。
7. 若需要 GUI，下載 DBeaver Windows x64 ZIP，解壓至 `.runtime/tools/dbeaver/`。
8. 執行環境驗證及 Jupyter 啟動指令。

本機 MySQL 設定與 kernel 含專案的絕對路徑；搬移整個專案後，需更新 `.runtime/mysql/my.ini` 並重新註冊 kernel。

如果全新環境的第一次初始化中途失敗，先看 `.runtime/mysql/initialize.log` 與 `mysql-error.log`。確認本專案的 mysqld 已停止、3307 端口空閒且尚無需要保留的匯入資料，再將 `.runtime/mysql` 改名保留為備份後重跑初始化。若 `scripts/db_config.py` 已存在，先確認是否其實已成功建置；勿直接重建既有資料庫。

Stage 4 的模型訓練、評估與推論已可執行，直接讀 CSV，不依賴 MySQL；詳見 [Stage 4 說明](STAGE4_DELAY_PREDICTION.md)。目前尚未使用 Retailrocket、FastAPI、Streamlit 或前端。

## 官方下載來源

- [MySQL Community Server](https://dev.mysql.com/downloads/mysql/)
- [MySQL Windows ZIP 安裝說明](https://dev.mysql.com/doc/refman/8.4/en/windows-install-archive.html)
- [DBeaver Community](https://dbeaver.io/download/)
- [DBeaver 26.2.2 發行檔](https://github.com/dbeaver/dbeaver/releases/tag/26.2.2)
- [Olist Brazilian E-Commerce Dataset](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce)
