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
| 後續工作 | 第二步已固定握手、證據閉合、路由與停止規則；實作及驗收另確認 |

機器可讀來源表與檔案描述見[來源評估收據](../reports/mainline/v79_role_exit_sources_20261117.json)。K1 完整驗收及 T_plan 仍未知，V46 暫不採用；每日 10% 與 Dashboard 優先順序不變。

## 第二步：最小接入、交付與下一輪邊界

### Q0 判定

Q0於2026-11-17 15:22:31完成文件方案與靜態審閱，從14:50:47起共31分44秒，在60分鐘界線內。這是本輪文件工作經過時間，不是工具耗時、校準或新實驗數字。

**Q0 已有明確的附條件方案，可交付給下一輪準備；不是「角色觀測能力已通過」。** 選 Windows 原環境的同一 handle 觀測，維持現有 `.venv` 啟動方式，不裝 Linux、不新增服務或監控程序。觀測者分工固定為：outer 觀測 pipeline；pipeline 觀測 worker 與 publisher。角色不能自證自己的退出碼。

| 靜態已解決 | 尚待後續獲准的合成驗收 |
| --- | --- |
| API、最小權限、handle 生命週期、整數／浮點轉換及失敗拒收 | 實際權限可用、FFI 簽名正確、現場 raw ticks 與 psutil float 相符 |
| ready／ack 時序、啟動關係核法、路由及證據閉合 | 快速退出與身份錯置確實被擋、三角色握手都接入、所有失敗路徑清理 |
| 原 196 案的新增 assertion 責任與單窗規格 | 原 196 案完整通過、64 prefix 恢復與完整輸出一致性 |

這些待驗項目是準備後的能力／接入判定，不可回填 V77 失敗、推算新耗時或宣稱 K1 真實完整驗收完成。

### 接入範圍與固定順序

未來另建版本化 native observer helper、pipeline／bundle／runner 與三個測試模組；不修改凍結 CP、V75 worker／fixture generator、V2／V4、SQL、原 manifest／golden／draws。新版工具的 source closure 必須收錄 observer helper、假 backend 及所有動態入口，不能只列新 pipeline。

1. **明確分流**：三個業務入口固定 `route=role` 並給明確 role、request、episode 與封存來源；A23 的 `-c` 人工命令明確 `generic_synthetic`。role 缺觀測不得降級走 generic，也不依 log／failure 檔名推定角色。泛用命令保留其原有 launcher exit／timeout／stop 判定，不假裝具備角色退出證據。
2. **監督者先建 launch**：選新 episode 與 nonce，寫入一次性 launch 後才 Popen。原 request deadline／累積 budget 及正式窗口截止不重設；每工作子程序 120 秒從 Popen 前開始，握手、核對、工作、等待與交付都算在其中。
3. **角色 ready**：共同入口在分派 `_worker/_pipeline/_publisher`、`_reenter`、開 CP／SQL、故障點或科學工作之前完成。只允許讀取及驗證握手所需的 request／launch／來源描述、取得自身身分、維持原期限檢查與寫 ready；原 `<role>_identity.json` 只寫一次，角色函式不再覆寫。ready 另存 raw creation 十進位字串；角色自查可用 [GetCurrentProcess](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-getcurrentprocess) pseudo handle，不能把它交給監督者或對它 CloseHandle。
4. **監督者核對後持有**：OpenProcess 取得角色 handle，核對 API PID／raw creation／舊三欄及 ready 綁定。使用下一節的同次啟動關係核法；所有成功開啟的 real handles 有唯一 owner。ack 前再以零等待確認 launcher／role 未退出，才原子寫入 ack。
5. **角色驗 ack 才工作**：ack 的 request、episode、role、nonce、ready／identity 描述符及 observer 必須逐欄一致；未知、缺漏、重複或過期 ack 都不能放行。等待受原預算限制，不開無限等候或獨立延長的握手時限。
6. **始終觀測同一 handle**：監督者沿既有檢點作零等待；使用既有有界輪詢／休息，不 busy-spin，不新開採樣器。只有 WAIT_OBJECT_0 後 API 成功才取得 exact-int DWORD；每次 API 失敗保存 API 名稱／錯誤碼，不讀未初始化輸出。角色已 signal 後，即使退出碼為 259 也不繼續等候。
7. **交付與清理**：把 role code 與 launcher code 分開保存。角色碼取得後仍須原 launcher 收尾與所有已觀測身分停態；非預期 launcher 錯誤、deadline veto 或 stop 不會被 role code=0 洗掉。成功只能在原截止前成立；逾時後只做清理與保存失敗，不進 CP finalize／正常交付。所有自開句柄在等待返回後由 owner 關閉一次；借用的 Popen 句柄仍由 Popen 擁有，缺失／關閉失敗留診斷並拒絕正常成功，不靠關閉句柄停止角色。

此 helper 未來可用標準庫 ctypes 接 Kernel32，須明訂 pointer-sized HANDLE、DWORD、BOOL、FILETIME 的 FFI 型別與 GetLastError 保存順序；這輪沒有建立或載入 DLL。觀測權限不含終止權，原停止／已觀測身分清理路徑仍獨立維持。監督者若中斷而遺失 handle，該角色碼即未知；重啟不能讀 JSON handle 數字或 reopen 舊 PID 補證。

### 同次啟動關係與競態界線

Popen launcher 的 handle／身分與 role 的 handle／身分分開。[CPython v3.12.10 subprocess.py](https://github.com/python/cpython/blob/v3.12.10/Lib/subprocess.py) 的 `_execute_child` 把 CreateProcess 回傳的 hp 存為 `Handle(hp)`／`self._handle` 並保存 pid；本案候選 adapter 保持 Popen 強參照，只借用 `int(Popen._handle)`，從該原 handle 核 GetProcessId==Popen.pid、GetProcessTimes raw creation 與零等待。不能改用後來 OpenProcess 同 PID 的結果作啟動根源。

借用者不 Close／Detach／重包成有所有權的 Handle，也不並行關閉；Popen 保有原 handle 所有權直到證據與清理收尾。新 OpenProcess 取得的角色／中間節點 handle 才由 observer 關閉一次。`_handle`／`Handle.closed` 是私有接面，只限定封存 CPython 3.12.10；缺欄位、型別不符、已關閉、API失敗或身分不符都不 ack，不能改用 PID fallback。0x00101000 只指新 OpenProcess 請求，不宣稱 Popen 原 handle 只有這些權限。版本／FFI 相容仍待驗。

若兩者相同，須以 PID、raw creation、舊三欄精確確認；不同時，從角色向上建立完整 parent chain，必須抵達本次 launcher。

每一節點都取得並持有 limited-query／synchronize handle，核對 PID、raw creation、正規化 create_time 與同一監督者的 CP boot 相容值，確認 nonsignaled；父 creation 不得晚於子。取得全部 handle 後，用**新的 parent snapshot／新的 Process 物件**重讀每一條邊，鏈必須相同；拒絕循環、缺節點、權限失敗、建立時間排序異常或 pre-ack 終止。root 必須精確綁本次 Popen launcher，不能只找到相同 PID。

[psutil 7.2.2](https://github.com/giampaolo/psutil/blob/release-7.2.2/psutil/__init__.py) 的 Windows ppid 會快取，重用同一 Process.ppid 不是新證據；parent／parents 的時間檢查也不能替代持續 handle。[底層 parent map](https://github.com/giampaolo/psutil/blob/release-7.2.2/psutil/arch/windows/proc.c)來自 Toolhelp snapshot。前後核鏈仍非原子 OS 親子證明，只限可信封存程式、無惡意偽造的合成範圍。不能宣稱防止同帳號造檔、parent spoof 或證明 V77 歷史鏈；不確定就拒收，不新增容差或 fallback。每個觀測到的鏈節點也加入後續停態清單，未觀測後代仍無全面保證。

### 外部路徑、寫入者與 schema

原 `EPISODE_FILES` 白名單不擴大，marker 留在既有 worker.log。新外部範圍固定為 `control/episodes/<episode>/roles/<role>/`，角色只允許 pipeline／worker／publisher，正常協定檔只有下表四個，另允許監督者一次寫入的失敗專用 delivery_veto.json；原 external `pipeline_exit.json` 保留位置但升版。episode 必須對應同一 internal episode；路徑穿越、別名、symlink、未知角色／檔案、重複或覆寫一律拒收。

| 檔案／唯一寫入者 | 必要欄位與核對 |
| --- | --- |
| launch.json／監督者 | versioned schema、role、episode、nonce、request 描述符、method／fixture seal 描述符、預期命令指紋、observer 舊身分；Popen 前寫一次 |
| ready.json／角色 | 綁 launch 描述符與 nonce、原 identity 檔描述符、native PID、canonical raw creation 字串；來源與 request 不得改綁 |
| ack.json／監督者 | 綁 launch／ready／identity 描述符，分列 launcher／role／observer 身分、raw creation、backend 版本、rights、fresh ancestry 兩次核對與 pre-ack nonsignaled 結果 |
| exit_observation.json／監督者 | 綁前述描述符，列 state、同 handle 的 signal／query 成功狀態、role exact-int code 或 null、launcher 身分與 code 獨立欄位、stop／deadline veto、failure 描述符、tracked 身分及觀測時間 |

共同型別規則：identity 保留原三欄並拒 bool PID；nonce 是本次唯一 token；描述符核 path／bytes／SHA；raw creation 只接受 canonical 十進位字串且解析在 epoch..uint64；role code 只接受 exact int 且在 DWORD 範圍，null 只代表未知。正常 role observation 須完整 launch→ready→ack、同 handle signaled／query 成功及無 stop；這只是 OS 退出證據，交付是否在期限內還要通過下節獨立守門。未能取得 handle、未 ack 或 API 失敗時只能留下 `state=unconfirmed`、null role code 與診斷；不能補造 ack 或已觀測碼。

既有 worker_exit／publisher_exit／pipeline_exit 使用新版 schema；identity／exit_code 只投影已核對的角色觀測，新增 launcher 與 observation descriptor。所有重複欄位逐項相等，normal_observed 不能僅 `code == 0`，也不能單獨作為交付完成授權。只有具來源的角色身分及 exact-int 0 能傳給凍結 CP finalize；非零由角色結構化錯誤傳遞。V77 歷史 JSON 不改寫。

### 寫檔跨期限、交付授權與恢復界線

退出觀測不等於交付完成。即使 receipt 寫前 code0／未逾時，落盤或 fsync 仍可能跨期限；也可能寫完後、最後 guard 前中斷。再加同一寫入者的 success marker 不能消除「最後一筆寫入」問題。因此固定以下有限方案，不把缺 veto 當成功證據：

- 每次 `_launch` 寫 observation／receipt、反讀核對、完成 owned handles 清理後，再檢查原 request／累積預算、從 Popen 前起算的120秒、正式900秒剩餘與資源守門；完成guard自身的budget持久化後，還須新讀UTC／monotonic作最後判定，不沿用guard寫前快照；此後不再有計入同次交付的寫入，通過才產生不可序列化的記憶體 delivery ticket。ticket不落盤，因此沒有「把最後成功檔案的落盤排除」的自循環；下一階段仍先核原守門，不因ticket而延長可工作時間。正常返回必須角色與launcher均exact-int0、無failure／stop；預期非零角色則由結構化例外攜帶已交付觀測的ticket／描述符，不能當正常返回。
- ticket 綁 request／episode／role／來源及 immutable observation descriptors，只能由該活監督者在上述控制流產生，validator須在原活observer的私有registry核同一物件身分及所有binding，不只驗isinstance或同形欄位；JSON或呼叫端自行建立的物件都不能成為ticket。這是可信封存程式的誤用拒收，不宣稱對抗同程序惡意碼。CP finalize／pipeline_result／正常外部交付必須持有適用ticket；不能單讀磁碟 code0 或 normal_observed 放行。
- 交付失敗後由原監督者一次保存 `control/episodes/<ep>/roles/<role>/delivery_veto.json`；最外 final seal 寫入／反讀後的guard失敗，保存 `control/final_delivery_veto.json`。內容綁 request／episode／角色或final-seal描述符、階段、原因、所用期限與原始錯誤，永不覆寫成成功；保存veto失敗也仍是失敗。兩處是精確失敗白名單，讀取優先於任何code0／seal。
- publisher／finalizer 必須檢查這兩類veto；歷史若有veto只能保留為失敗證據，不能重新授權那次交付。最終seal封外部固定證據及當時veto集合；之後多出veto即否決，不因它晚到而忽略。`control/final_delivery_veto.json` 位於不可變觀測集合的明確附加路徑，budget仍不封成整包。
- 最外 `run_pipeline` 寫 final_seal 並反讀後也要guard及其持久化後的新時鐘判定，才返回活ticket。正式套件最終由現有外部 formal runner 核套件正常退出、完整196結果、已觀測停態及900秒期限；result落盤後另有原正式deadline_veto。公開collector須核正式入口實際退出狀態與所有veto。**raw final_seal 單檔不代表整窗成功**；外部入口中斷或結果不完整一律未知／失敗，不補造成功。

A18 的原 normal_worker_exit 是封存控制流在 worker 交付ticket成立後才進 CP.finalize 所留下的後續證據；仍須唯一回溯原worker observation，且其supervisor等於該episode pipeline角色。A22.P10既有案例是在同一outer程序呼叫兩次入口，可保留該活outer的已核ticket完成原重入；`_completed_episode` 必須搭配該ticket，不能只讀舊磁碟receipt。A20唯讀篡改案例則核已保存的完整控制流／觀測鏈，不自行製造新的交付ticket。`finalize_stopped(expected=...)` 必須分成純反讀路徑，不因_completed_episode的活ticket要求而重設期限、重開角色或補寫seal；原A21同outer反讀沿用原ticket。跨outer純反讀只報bytes／chain一致性及既有正式窗口權威，缺後者則delivery unknown；不mint ticket、不補seal、不新增成功。

**尚未支持的恢復範圍：若outer真的崩潰並遺失ticket，只餘未確認的P10檔案，本最小方案拒收為未知，不保證跨outer重啟自動完成P10。** 要支持該範圍須另訂外部獨立delivery acknowledgment；不以增加同一寫入者的成功檔冒充解決。原196案例中的同outer P10恢復期待保留，但不能外推為完整崩潰恢復覆蓋；這個缺口必須留在K1後續完整驗收清單。

### publisher 與 final seal 的閉合責任

現有 `audit_saved` 只找 internal worker_exit；`finalize_stopped` 只另封 external pipeline_exit；A20 的 `_copy_science` 只複製 internal。三者均須更新，新證據不能只留旁邊而未反核。

| 時點 | 反核與保存 |
| --- | --- |
| publisher 開始（H7 前） | 固定已完成 worker／歷史角色的完整 observation 集合，加上目前 pipeline／publisher 的 launch／ready／ack。當前尚未結束的角色不得要求自身 exit |
| publisher 結束前（H8 後） | 再核上述固定前綴 path／bytes／SHA 完全一致，寫入 publisher_proof；不重跑排名、global 或 draws |
| publisher／pipeline 結束 | 各自監督者依序補 publisher exit 及 pipeline exit；不能回頭改已固定的 prefix |
| 外部 finalizer | 精確核全 internal 與外部 observation 白名單；publisher prefix 不變，只允許預先列出的當前 publisher／pipeline exit 後綴補齊；兩次 snapshot 一致、全部已觀測身分停止，才寫最終 seal；交付另須上節post-write ticket |
| 完成後反讀 | 外部觀測也列入 seal 的完整 path／bytes／SHA，新增、缺失、append 或內容改動均拒收；完成入口同樣要求 exact-int 0、完整觀測與無 stop／deadline veto |

已完成的歷史 episode 可有原案例預期的非零退出，必須保存其完整故障／觀測鏈，不能一律抹成正常。未曾啟動的 role 不產生假檔案；每 episode 的角色集合由 launch 與實際控制分支核對，缺少應有角色或多出角色都拒收。當前成功 episode 必須有正常 pipeline／publisher；若沿用原 normal_worker_exit，須追到原 episode 的完整 worker 角色證據，不能只相信 CP 內的 copy；candidate worker identity必須唯一對應一筆原episode observation，normal_worker_exit的supervisor須等於該episode pipeline角色。

`control/budgets` 仍可依原契約更新，不能把整個 control 都當不可變；`control/case_evidence` 的假工具 assertions 由正式 runner 個別封存，也不冒充角色 OS 觀測。A20 複製人工 run 時，須複製對應外部 observation 及其路徑結構，才有資格驗新閉合／篡改拒收。複製保留原run／request／episode／nonce與協定bytes，描述符使用run-root相對路徑；不因測試目錄改變就重寫launch／ack或命令指紋。

### 原案例與精確退出判定

原 34 方法語義映射、196 IDs 同序、24 族及三個模組保留；新 assertions 放回既有 case 內，不新增／重複 case event，不因增加 assertions 改稱案例數增加。原 A09 缺 DB 精確例外與拒收鏈保留。

| 原案例 | 必須補驗的責任；原期待仍保留 |
| --- | --- |
| A12.prefix_crash_recovery | V78 W1–W7 與 E1–E6／P；先驗假 checker，再確認真正 worker=9、pipeline=1、同一角色 marker 第65次、無非預期 worker_failure／stop；先核64有效prefix才准恢復 |
| A16.alive／nonzero／pid_reused／uncertain／other_boot／self_exit | 假 native backend 的 handle、raw ticks、型別、身份／observer、缺 ack、未知退出與 API 失敗；原 CP 拒收不變 |
| A20.request／request_deadline／normal_boot／observed_exit／no_numeric_replay | 新外部證據綁定、缺 ack、role／launcher錯置與篡改拒收；不新增科學重播 |
| A21.closed_manifest／extra／append／missing／live | 外部白名單、缺檔／多檔／late append、固定前綴、已觀測身分停態；補假backendowned handle單次CloseHandle、borrowed launcher零次close與失敗清理 assertions |
| A23.absolute／downtime／rollback／delivery／path_scope | 握手／等待／保存全部消耗同一原期限；未 ack 不工作、快速退出拒收、late code0不能洗掉逾時、新路徑範圍 |
| A23.resource_process／monitor_process／descendant_timeout | 明確 generic 路由，保留原 launcher failure／stop／timeout／後代清理期待；不要求假命令裝成業務角色 |
| A17／A18／A19／A22 | 維持 candidate未知退出、已記正常退出恢復、來源位置及發布恢復原意；跨episode回溯新觀測證據 |

假 backend 須涵蓋 Open／GetProcessId／GetProcessTimes／wait／GetExitCodeProcess／close 的成功與失敗、bool／float／字串退出碼拒收、signaled259拒收、啟動鏈變動與舊 ppid 快取不可冒充 fresh 重讀。這些在未來同一正式窗口、原 case ID 內執行，不在封存前做能力小試。假API assertions通過也不能代表真API權限與握手已通過。

A12 第一段的 pipeline_failure 須結構化綁 `failed_child_role=worker`、worker observation 描述符、exact-int9 及 nontimeout；不能只匹配 RuntimeError 字串。marker flush／fsync 後才 os._exit(9)，marker 只是故障點證據。E全部成立後，保存恢復前 snapshot，驗 chunk0／64筆／ordinal0..63／previous SHA null／原 golden prefix；第65筆未提交尾巴可存在但不算有效prefix。任一不符都不能呼叫第二次入口。第二次沿同 request／run／來源／deadline／累積預算，舊 chunk bytes不變、完整129／2000 draws及三角色正常0／完整發布停態均須成立。

### 停止條件、估時與待確認範圍

| 關卡 | 界線與停止條件 |
| --- | --- |
| 本輪 Q0 | 最多60分鐘；若截止仍沒有上述具體來源／協定／閉合方案就停。本輪已有方案，完成文件即停，不自動準備工具 |
| 未來工具準備 | 另確認後才開始；原120分鐘檢點不放寬。屆時若來源閉包、路由、證據閉合、34／196／24映射或封存尚未完成，保存缺口並停，不為趕時間刪案例或先試跑 |
| 未來正式窗口 | 另確認且工具／原人工來源封存推送後，最多一次完整窗口900秒、每工作子程序120秒且受剩餘時間約束；含所有假backend與真入口案例，失敗／逾時不補跑 |
| 任一階段 | 權限或API未知、身份／raw ticks／boot不符、缺fresh鏈／ack／觀測、證據不閉合、來源變動、缺／重複／跳過必要案例、額度或外部中斷即保存並停止相依工作；不增權、不換runtime或放寬CP |

工程估計需修正：工具及整合靜態複核約 **100–160分鐘**，封存、至多一次完整窗口、反核及README／Git約 **30–40分鐘**，合計 **130–200分鐘**。這是依新增外部閉合、A20複製與三角色握手範圍作的規劃估計，沒有實測；機器執行2–10分鐘仍是未驗估計，不用V77部分窗口94.047秒外推。原準備120分鐘上限維持，故可能到時只交未完成項而尚未封存／開窗，不能以估時上調自動延長。

**下一輪建議只確認「準備並封存新版工具與原案例，120分鐘仍未封存即停，不執行驗收」；完成後再決定是否授權唯一900秒窗口。** 這樣可先讓變更與完整196案例映射可審查。使用者本次明定先不實作／啟動／驗收，因此本輪到Q0文件交付為止；不是工具或執行授權。

本輪共引用第一步20份與第二步2份官方來源；靜態審閱涵蓋上述借用handle、交付ticket／veto及P10限制。機器可讀的固定順序、schema、路由、案例映射與界線見[最小接入提案](../reports/mainline/v79_role_exit_integration_proposal_20261117.json)。本輪沒有新增通過案例或科學成績，原golden與196子案例完整保留；不重跑真實資料，K1完整驗收／T_plan仍缺，V46暫不採用。

第二步完成時，10份來源描述、34方法／196同序IDs／24族／3模組及27個既有案例映射均完成檔案層核對；來源／身分、Win32與期限交付、整合／純反讀三方面靜態審閱通過。只新增文件與規格收據，未實作或執行任何專案驗收。
