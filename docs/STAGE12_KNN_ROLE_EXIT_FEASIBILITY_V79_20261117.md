# V79｜Q0 角色退出觀測來源與最小接入可行性

本輪依 V78 只做文件及原碼可行性評估。Q0 自 2026-11-17 14:50:47（Asia/Taipei）起算，最遲 15:50:47 仍無明確方案即保存缺口並停止。沒有實作觀測工具、載入 suite、呼叫程序／SQLite／checkpoint API、啟動角色或測試程序，也沒有新增量測。文件整理所用的檔案讀寫與雜湊核對不屬於程序能力驗收。

## 第一步：來源語義與身分相容性

**已找到附條件的靜態可行方案：由現有監督者在角色開始工作前，取得並持續持有真正角色的 Windows process handle；待同一 handle 顯示終止，再讀角色退出碼。** 啟動程序的 Popen returncode 另存，不拿來代填。這是由官方語義推導的待實作協定，尚未通過現場能力、入口接入或合成驗收。

### 官方來源能支持什麼

| 來源 | 本案可採用的語義 | 限制 |
| --- | --- | --- |
| [OpenProcess](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-openprocess)、[權限表](https://learn.microsoft.com/en-us/windows/win32/procthread/process-security-and-access-rights) | 依 PID 開啟本機 process object；候選只需 SYNCHRONIZE 與 PROCESS_QUERY_LIMITED_INFORMATION，合計 0x00101000，bInheritHandle=FALSE | 權限可能被拒絕；不要求 all-access、debug privilege 或新增管理員權限 |
| [GetProcessId](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-getprocessid)、[GetProcessTimes](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-getprocesstimes) | 從同一 handle 取得 PID 與 creation FILETIME，兩者均接受 limited-query | API 成功才可用輸出；未退出時不能使用 exit-time 欄位；這輪不採集 CPU 時間 |
| [FILETIME](https://learn.microsoft.com/en-us/windows/win32/api/minwinbase/ns-minwinbase-filetime) | 高低 DWORD 組合為精確整數，單位是自 1601 年起的 100 ns | 表示單位不等於實際解析度，也不是全域唯一 ID |
| [WaitForSingleObject](https://learn.microsoft.com/en-us/windows/win32/api/synchapi/nf-synchapi-waitforsingleobject) | 零等待可查 signaled；有限等待須受原期限約束；WAIT_FAILED 要保留錯誤 | 不用 INFINITE；等待尚未返回時不能關閉 handle；Windows 8 起 timeout 不計低電力時間，不能單靠 wait 保證整關 wall 上限 |
| [GetExitCodeProcess](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-getexitcodeprocess) | 同一 handle 已 signaled 且 API 成功後，DWORD 才作角色退出證據 | API 的 BOOL 成敗與退出碼不同。不能以 STILL_ACTIVE=259 判活；signaled 後若得到 259，保存原值並依本案 0／1／9 契約拒收 |
| [Handle 與 PID](https://learn.microsoft.com/en-us/windows/win32/procthread/process-handles-and-identifiers)、[程序終止](https://learn.microsoft.com/en-us/windows/win32/procthread/terminating-a-process) | 外部持有的 handle 可在角色終止後繼續指向同一物件；終止會 signal 並設定退出狀態 | 不宣稱 PID 永不重用；不得中途丟棄 handle，再按舊 PID reopen 補碼；父程序終止不保證後代都停止 |
| [CloseHandle](https://learn.microsoft.com/en-us/windows/win32/api/handleapi/nf-handleapi-closehandle)、[Kernel Objects](https://learn.microsoft.com/en-us/windows/win32/sysinfo/kernel-objects) | 單一持有者負責成功開啟 handle 的關閉，包括失敗路徑 | handle 數字不是可寫入 JSON 後跨程序或重啟恢復的憑證；關閉 handle 不等於停止角色 |

上述 API 不知道專案的 request、episode、科學角色或輸出是否完成；角色綁定與發布帳本仍需獨立核對。PID／creation time／nonce／啟動關係用於本案可信工具的錯置與競態拒收，不宣稱能抵抗同使用者惡意偽造。

### 保留舊身分格式，新增精確觀測欄位

凍結 CP 的 identity 仍是 pid／create_time／boot_time 三欄，`<role>_identity.json` 不加欄位。新外部 ready 證據另綁該檔描述符與角色自查的 raw creation ticks（JSON 使用無符號、無前導零的十進位字串，避免其他讀取端轉浮點失真）；監督者從自己持有的 handle 讀取 raw ticks，必須精確相等。

psutil 7.2.2 的 [FILETIME 轉換原碼](https://github.com/giampaolo/psutil/blob/release-7.2.2/psutil/arch/windows/init.c)先以整數組合 ticks，再減整數 epoch offset 116444736000000000，最後轉 double 除以 10000000。因此相容映射固定為 `float(raw_ticks - 116444736000000000) / 10000000.0`；拒收 epoch 前或超出 unsigned 64 範圍的值。不得先把 ticks 轉浮點再扣秒數、round、毫秒化或使用容差；不能從舊浮點值反推出 raw ticks。

舊 create_time 必須與此映射精確相等，且角色、監督者使用同一已封存 runtime。[一般路徑](https://github.com/giampaolo/psutil/blob/release-7.2.2/psutil/arch/windows/proc.c)的 psutil_proc_times 使用 GetProcessTimes；[fallback](https://github.com/giampaolo/psutil/blob/release-7.2.2/psutil/arch/windows/proc_info.c) 的 psutil_proc_info 使用 SystemProcessInformation/CreateTime，兩者都進入相同轉換函式。官方 tag 與本機 Python 包裝文字只能支持靜態解讀，**不能當成已安裝原生 binary 的建置來源證明或本輪 runtime 實測**。

既有 `Processes.boot_identity()` 在 Windows 呼叫 NtQuerySystemInformation(3)，要求 48 bytes，再讀前 8 bytes。Microsoft [文件](https://learn.microsoft.com/en-us/windows/win32/api/winternl/nf-winternl-ntquerysysteminformation#system_timeofday_information)僅公開 opaque 48-byte reserved 結構，未保證 class 3 數值及前 8 bytes 的 BootTime 語義，並明言內部 API／結構可變。本案保留凍結 CP 的嚴格相等與失敗拒收，不改用 psutil.boot_time()、容差或新 boot ID；新退出觀測的核心是開始工作前核對並持續持有的同一 handle，boot 欄位只保留原相容守門。未來若 boot 讀取或相等檢查失敗，就停止，不能在本範圍內修 CP 或忽略它。

### 啟動中介的來源線索與不能推論的部分

本機 `.venv/pyvenv.cfg` 文字宣告 Python 3.12.10，V77 已保存的 runtime 為 Windows／CPython 3.12.10／psutil 7.2.2。這輪只讀配置，未啟動 Python 入口來查 runtime。

CPython v3.12.10 的 [venvlauncher 建置設定](https://github.com/python/cpython/blob/v3.12.10/PCbuild/venvlauncher.vcxproj)與 [launcher.c](https://github.com/python/cpython/blob/v3.12.10/PC/launcher.c)包含 VENV_REDIRECT、建立子程序並等候／取得其退出碼的路徑。因此虛擬環境啟動中介是「PID 不同」的合理候選解釋；V77 既有紀錄沒有保存每一節點的 executable／binary 對應，不能據此斷言當時實際鏈或把歷史 launcher code 回填成 role code。

不選直接改用 base interpreter：那會牽動 `.venv` 與套件載入／方法來源，超過最小退出觀測修正。也不選事後 PID 輪詢、psutil.wait 的缺碼結果、故障 marker 或 launcher forwarding 作獨立角色碼的替代來源。

### 本步實際狀態

| 項目 | 狀態 |
| --- | --- |
| OS 來源與最小權限 | 已有官方文件支持的候選方法，尚未呼叫 API |
| 舊身分相容 | 已固定整數／浮點轉換順序；boot 私有語義與 runtime 相容限制保留 |
| V77 歷史退出碼 | 不改判、不回填；147 通過／1 失敗／48 未執行原狀 |
| 原 golden 與案例 | 原封存來源、34 方法／196 子案例／24 族保留；沒有重產或重跑 |
| 後續工作 | 本輪還要固定握手、證據閉合、路由與停止規則；實作及驗收另確認 |

機器可讀來源表與檔案描述見[來源評估收據](../reports/mainline/v79_role_exit_sources_20261117.json)。K1 完整驗收及 T_plan 仍未知，V46 暫不採用；每日 10% 與 Dashboard 優先順序不變。
