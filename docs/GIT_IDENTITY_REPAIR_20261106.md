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
| 歷史改寫與逐筆驗收 | 尚未執行 |
| 遠端強制推送與 GitHub 歸屬核對 | 尚未執行 |

GitHub 貢獻圖需使用連結至帳號的作者 Email，並位於預設分支；符合條件後可能需要最多 24 小時更新。本輪還未完成歷史改寫，不能聲稱綠格子已恢復。[GitHub 官方說明](https://docs.github.com/en/account-and-profile/how-tos/contribution-settings/troubleshooting-missing-contributions)
