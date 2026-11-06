# GitHub 提交身分整理（2026-11-06）

## 帳號與原始盤點

GitHub 已登入帳號為 `likaisuwork9616`，個人資料 Email 為 `likaisu.work9616@gmail.com`，本專案遠端屬於同一帳號，具有管理與推送權限。遠端只有 `main`，沒有標籤；整理前本機與遠端同為 `b89b46e2e4f879ad7a2d2b04176411f6f9450adf`，工作目錄乾淨。

| 原始 main 歷史 | 作者 Email | 提交者 Email |
| --- | ---: | ---: |
| `151002@tw.dmi` | 119 | 119 |
| `likaisu.work9616@gmail.com` | 35 | 35 |
| 合計 | 154 | 154 |

154 筆均未簽署；原作者日期從 2026-06-20 到 2026-11-06。這次保留原日期、時間與時區，不補造貢獻日。

已將此專案本機 Git 身分固定為 `LiKaiSu9616 <likaisu.work9616@gmail.com>`，作者與提交者設定均已實際核對。設定採 repository-local，後續不再依賴電腦自動猜測名稱／Email。

## 備份與改寫範圍

`shop-mysql-runtime/verification/git-identity-repair-20261106/original-main.bundle` 已建立並通過 `git bundle verify`，保存整理前完整 main 歷史。備份、完整對照與執行狀態留在 Git 忽略路徑，不隨 repository 上傳。

採用專案 `.venv` 內的 `git-filter-repo 2.47.0`，在新建隔離副本中，將原 `151002@tw.dmi` 的作者及提交者統一為上述 GitHub 身分；原本正確的 Gmail 身分保持一致。只處理這個專案的 main，不改動其他專案或桌面工具的內部 refs。

改寫後逐筆驗證 commit 數量、檔案 tree、訊息位元組、原日期／時區及父子拓樸。推送採指定舊 main SHA 的 `--force-with-lease`，若遠端已新增提交會拒絕覆蓋。GitHub commit SHA 將改變，原 SHA 對照會保存；內容雜湊及已封存的研究報告不因身分整理而改寫。

| 階段 | 狀態 |
| --- | --- |
| 帳號／Email 與歷史盤點 | 完成：119 筆需修正、35 筆原本正確 |
| 本機未來身分與完整備份 | 完成，備份驗證通過 |
| 歷史改寫與逐筆驗收 | 完成：含盤點共 155 筆，119 筆作者及提交者修正，120 個 SHA 改變 |
| 遠端強制推送與 GitHub 歸屬核對 | 尚未執行 |

GitHub 貢獻圖需使用連結至帳號的作者 Email，並位於預設分支；符合條件後可能需要最多 24 小時更新。歷史已完成本機改寫，GitHub 歸屬與綠格子仍待發布後核對。[GitHub 官方說明](https://docs.github.com/en/account-and-profile/how-tos/contribution-settings/troubleshooting-missing-contributions)

## 歷史改寫驗收

隔離副本實際執行 `git-filter-repo --mailmap ... --preserve-commit-hashes --preserve-commit-encoding --prune-empty never --prune-degenerate never --replace-refs delete-no-add`。原本 119 筆舊身分全部改為 `LiKaiSu9616 <likaisu.work9616@gmail.com>`；原 35 筆正確身分保持相同，新增盤點提交也使用正確身分。

含盤點共 **155 筆**，逐筆讀取原／新 Git commit 原始物件，只替換核准身分及必要的父 SHA 後逐位元組比較，**155／155 通過**。因此每筆 tree、訊息、日期／時區及父子拓樸均一致。120 個 SHA 改變，35 個未變；整理前後 head tree 同為 `f3724c7597960c084cc44598bd4a143b1f30c490`。

重寫前 main `c775402d465e9b273586461494f5bb596e2d01e2` 對應新 main `168606f9efaa6a976afb9abc99e7fc4be3c0872b`。本次結果文件提交會再接在新 main 後；遠端發布採固定舊 SHA 的 force-with-lease。

[完整驗收與 155 筆新舊 SHA 對照](../reports/maintenance/git_identity_rewrite_20261106.json)。歷史文件中的舊 commit 連結保留原記錄，可用對照查新 SHA；不改寫已封存研究產物。

另已建立、驗證 `shop-mysql-runtime/verification/git-identity-repair-20261106/pre-rewrite-main.bundle`（含盤點提交）。需要還原時，可先在另一資料夾用 `git clone <此 bundle 的絕對路徑> <新資料夾>` 檢查原歷史，再決定是否恢復遠端；不要直接用備份覆蓋後續新工作。
