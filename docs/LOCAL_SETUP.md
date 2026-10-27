# 本機環境與操作方式

此環境建置於 `E:\kai_work\kai自己的\shop`，供 Olist 資料匯入、SQL、EDA 與 Stage 4 模型實驗使用。

## 本機環境基準

下表記錄已建置的本機版本與位置；套件重現以`requirements-lock.txt`為準，研究進度另見[專案進度](PROJECT_PROGRESS.md)。

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
| DBeaver Community | 尚未安裝；選用的資料庫 GUI |
| MySQL Connector/J | 尚未安裝；使用 DBeaver 時另行設定 |
| Olist 原始資料 | `data/raw/olist/`，9 個官方 CSV |

MySQL ZIP 已比對官方 MD5，下載檔保存在 `.runtime/downloads/`。MySQL 沒有註冊 Windows 開機服務。Olist 使用官方 Kaggle 第 2 版，九份 CSV 的大小、SHA-256 與實際筆數記錄在 `.runtime/verification/olist-source-manifest.json`。

Python 套件（包含 XGBoost、LightGBM）都安裝在 `.venv/`。MySQL 是獨立程式與服務，程式、資料與設定放在 `.runtime/`，不屬於 Python 虛擬環境。重新建立 Python 環境可使用 `requirements-lock.txt`；該鎖定清單對應目前的 Windows x64／Python 3.12。

目前專案路徑含中文，MySQL Windows 程式讀取這類選項檔／資料目錄路徑時會失敗，因此使用 ASCII 路徑 `E:\kai_work\shop-mysql-runtime` 作為本專案 `.runtime` 的目錄 junction。資料仍儲存在專案內；`my.ini` 的 `basedir`、`datadir`、`log-error`、`pid-file` 使用 junction 路徑。啟停腳本會先讀取專案內的 `my.ini`，再沿用設定中的路徑呼叫 MySQL 與管理員設定檔。

2026-10-27 已在此路徑完成重建：116 個鎖定套件、九張資料表共 1,550,922 筆，以及四本 Notebook 全部 59 個程式區塊均通過實測。01–03 另產生 8 張 EDA 圖表，副本與結果保存在 `.runtime/verification/`。資料庫與 01–03 的摘要是 `summary.json`，04 的摘要是 `notebook04-verification.json`；完整本機驗收見 `full-setup.json`。

MySQL 停止、重啟、重複啟動與重啟後九表筆數核對均通過，紀錄在 `mysql-restart.json`。JupyterLab 以正常啟動腳本實測 HTTP API、四本 Notebook 根目錄、`.venv` kernel 建立與 Lab 頁面均通過，紀錄在 `jupyter-server.json`；驗證後已關閉測試 Jupyter，MySQL 保持運行。

04 所需的模型為本輪僅用原訓練集 54,145 筆重建的教學模型，來源與切分已核對。它不是原凍結研究 artifact，沒有重新預測或評估驗證集／保留測試集，Notebook 顯示的歷史成績仍來自既有報告。重建紀錄在 `.runtime/verification/notebook04-model-rebuild.json`。

模型訓練、回測、校準與診斷使用同一份`.venv/`，但每個入口的前提與寫入產物不同，請先查[腳本導覽](../scripts/README.md)及[研究文件](README.md)。這份指南只維護安裝與服務操作，歷史fit數、測試數及成績保留在當輪文件。Notebook執行副本與摘要存於`.runtime/verification/`，提交版清除輸出。

## 開始分析

在專案根目錄的 PowerShell 執行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_jupyter.ps1
```

這個指令會先啟動本專案的 MySQL，再開啟 JupyterLab。Notebook 工作目錄設為 `notebooks/`，符合前三本 Notebook 使用 `Path.cwd().parent` 的寫法。請選擇 `Shop (Python 3.12)` kernel，先依序閱讀`01`、`02`、`03`；`04`的資料與模型前提另見[Notebook導覽](../notebooks/README.md)，缺原版artifact時可能自動觸發訓練。

Jupyter 使用 `127.0.0.1:8888`，保留預設登入 token；若瀏覽器未自動開啟，可使用終端顯示的完整網址。按 `Ctrl+C` 關閉 Jupyter 後，MySQL 仍會執行。

需要單獨啟停資料庫時：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_mysql.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\stop_mysql.ps1
```

## DBeaver

本輪未安裝 DBeaver；目前可使用 Jupyter 的 SQL Notebook 查詢資料庫。若要使用 GUI，先另外安裝 DBeaver 與設定 JDBC driver，再使用下列啟動入口：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_dbeaver.ps1
```

啟動腳本使用專案內的 workspace，DBeaver 全域設定也導向 `.runtime/DBeaverData`。連線名稱可設為 `Olist local (127.0.0.1:3307)`；第一次連線時，請從 `scripts/db_config.py` 讀取密碼並輸入。

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

額外重新執行`01`–`03`三本Notebook的副本（不含`04`）：

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
4. 執行 `.\.venv\Scripts\python.exe scripts\setup_local_mysql.py`。這只用於全新環境，偵測到既有資料或連線設定就會停止，避免覆寫。若專案路徑含中文，先依下節建立 ASCII junction，再加上 `--runtime-root`；此選項只接受已存在且實際指向本專案 `.runtime` 的路徑，不會自行建立外部 junction。
5. 從 Olist 官方 Kaggle 頁下載資料，將 9 個 CSV 放入 `data/raw/olist/`，再執行匯入指令。
6. 執行 `.\.venv\Scripts\python.exe -m ipykernel install --sys-prefix --name .venv --display-name "Shop (Python 3.12)"`。
7. 若需要 GUI，下載 DBeaver Windows x64 ZIP，解壓至 `.runtime/tools/dbeaver/`。
8. 執行環境驗證及 Jupyter 啟動指令。

本機 MySQL 設定與 kernel 含專案的絕對路徑；搬移整個專案後，需確認 junction 指向搬移後的 `.runtime`，更新 `.runtime/mysql/my.ini` 中的 `basedir`、`datadir`、`log-error`、`pid-file` 並重新註冊 kernel。先停止本專案 MySQL，再處理 junction；不要對指向資料目錄的 junction 執行遞迴刪除。

### 中文路徑的全新環境初始化

以下是目前路徑的首次建立範例。已建置的環境不需重跑；alias 路徑若已存在，指令會停止，請先確認其用途與目標，不能覆寫既有路徑。

```powershell
$projectPath = 'E:\kai_work\kai自己的\shop'
$runtimePath = Join-Path $projectPath '.runtime'
$mysqlAlias = 'E:\kai_work\shop-mysql-runtime'
if (Get-Item -LiteralPath $mysqlAlias -Force -ErrorAction SilentlyContinue) {
    throw 'Alias path already exists; inspect it before continuing.'
}
if (!(Test-Path -LiteralPath $runtimePath -PathType Container)) {
    New-Item -ItemType Directory -Path $runtimePath | Out-Null
}
New-Item -ItemType Junction -Path $mysqlAlias -Target $runtimePath | Out-Null
Set-Location -LiteralPath $projectPath
.\.venv\Scripts\python.exe scripts\setup_local_mysql.py --runtime-root $mysqlAlias
```

`--runtime-root` 會保留 alias 的文字路徑寫入 MySQL 設定，仍使用原本的防覆寫與本機端口檢查。路徑驗證不會啟動資料庫；實際初始化只供尚未建立資料庫的環境使用。

如果全新環境的第一次初始化中途失敗，先看 `.runtime/mysql/initialize.log` 與 `mysql-error.log`。確認本專案的 mysqld 已停止、3307 端口空閒且尚無需要保留的匯入資料，再將 `.runtime/mysql` 改名保留為備份後重跑初始化。若 `scripts/db_config.py` 已存在，先確認是否其實已成功建置；勿直接重建既有資料庫。

Stage 4 的模型訓練、評估與推論已可執行，直接讀 CSV，不依賴 MySQL；詳見 [Stage 4 說明](STAGE4_DELAY_PREDICTION.md)。目前尚未使用 Retailrocket、FastAPI、Streamlit 或前端。

固定每日10%研究及最新診斷入口集中於[腳本導覽](../scripts/README.md)。不需要為驗證環境就重跑歷史訓練；原始資料、逐筆分數、模型與日誌保持Git忽略，正式聚合報告與實驗路徑依原規格保留。測試命令見[測試說明](../tests/README.md)。

## 官方下載來源

- [MySQL Community Server](https://dev.mysql.com/downloads/mysql/)
- [MySQL Windows ZIP 安裝說明](https://dev.mysql.com/doc/refman/8.4/en/windows-install-archive.html)
- [DBeaver Community](https://dbeaver.io/download/)
- [DBeaver 26.2.2 發行檔](https://github.com/dbeaver/dbeaver/releases/tag/26.2.2)
- [Olist Brazilian E-Commerce Dataset](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce)
