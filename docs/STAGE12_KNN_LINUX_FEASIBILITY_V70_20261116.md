# Stage 12｜V70 Linux 環境可行性與接入提案

依 [V69](STAGE12_KNN_OBSERVATION_SOURCES_V69_20261116.md)保留原 **1 ms 目標、同一 thread 的 user＋system CPU 時長、相同程式邊界與驗收門檻**。本輪僅閱讀官方文件與既有程式／收據，提出待確認方案；不探測本機、不啟動 WSL／VM／容器、不下載／安裝／建置、不準備工具或合成案例，也不執行測試、時鐘讀取、B／C／D、model 或原固定48筆。原V62–V69保持原樣，V67仍能力未確認，V46暫不採用。

## 平台可行性：有條件可規劃，尚未證明可用

**文件層首選 P1：可供研究使用的原生 Ubuntu Server 24.04 LTS amd64，GA 6.8 核心軌道，本機 Linux 檔案系統。**這是減少虛擬化與跨系統檔案存取變因的工程選擇，不是較快、較準或必能通過1ms門檻的結論。目前未取得可用主機資訊；沒有假定要購機、重灌或分割磁碟。

**若只能沿用 Windows，次選 P2：WSL 2＋Ubuntu 24.04 LTS amd64。**它使用 Microsoft 管理的 Linux kernel 與 VM，不能稱為原生Ubuntu或套用P1的GA6.8。若採P2，須以獨立環境ID評估；不能自動替代P1或將兩者資料合併。

| 方案 | 官方文件事實 | 本案可行性判定與未知 |
| --- | --- | --- |
| P1 原生 Ubuntu Server 24.04 LTS amd64 | 24.04首發含kernel6.8、glibc2.39、Python3.12；Server預設GA、Desktop預設HWE，後續point release／套件會更新 | 首選研究範圍；具體主機、安裝來源、kernel完整revision、libc、CPU／記憶體／磁碟及使用權限尚未知。不是要求重灌現有Windows。[發行說明](https://documentation.ubuntu.com/release-notes/24.04/)、[kernel軌道](https://ubuntu.com/kernel/lifecycle) |
| P2 WSL 2＋Ubuntu 24.04 LTS amd64 | WSL2有真實Linux kernel及受管VM；distro版本不決定kernel；`.wslconfig`是全域設定 | 可沿用Windows主機的條件方案，但可用性、虛擬化支援／權限、WSL與host版本未確認。要另綁host／VM資源設定；不擅改全域配置。[架構](https://learn.microsoft.com/en-us/windows/wsl/compare-versions)、[設定範圍](https://learn.microsoft.com/en-us/windows/wsl/wsl-config) |
| P3 一般VM＋Ubuntu Server 24.04 | VM具有自己的OS與kernel | 須另指定hypervisor、guest、vCPU、記憶體模式及host；多一層排程與資源條件，初始方案不優先，也未證明不能通過。[VM與容器](https://docs.docker.com/get-started/docker-concepts/the-basics/what-is-a-container/) |
| P4 Linux容器／Windows Docker Desktop | Linux容器共用執行所在kernel；CPU quota／cpuset／shares影響資源。Windows Desktop的WSL2後端另含VM | image digest不能固定host kernel與排程；初始接入沒有此包裝需求，不列優先。若未來採用，需另綁host、backend、cgroup與runtime，不當作P1。[容器](https://docs.docker.com/get-started/docker-concepts/the-basics/what-is-a-container/)、[資源限制](https://docs.docker.com/engine/containers/resource_constraints/)、[Desktop WSL2](https://docs.docker.com/desktop/features/wsl/) |

P2的工作副本、`.venv/`與私人證據應位於Linux檔案系統，提案位置為Linux帳號下的獨立 `shop-linux-observation` 工作副本；不直接從原 `/mnt/e/...` 工作目錄執行計時。官方建議Linux工具將專案放在WSL檔案系統；本案據此避免跨系統檔案路徑成為額外變因。這不是已建立的目錄。[Microsoft檔案系統說明](https://learn.microsoft.com/en-us/windows/wsl/filesystems)

WSL1不列本案Linux kernel候選；原生、WSL2、一般VM及容器的可用性與能力都不能由名稱推定。選定後仍須按V69確認實際來源與metadata，再依序驗收，不能因平台改名而降低q或bracket門檻。

## 具體 runtime 提案

**R1：upstream CPython 3.12.10 source release，Linux x86_64 release build，PGO／LTO／Py_DEBUG關閉。**保留V67已存的patch版本，降低一項版本差異；不宣稱同Windows binary或同建置最佳化。它是舊版研究runtime，官方已列3.12.16取代；提案限隔離合成研究，不作對外服務runtime。[3.12.10](https://www.python.org/downloads/release/python-31210/)、[3.12.16](https://www.python.org/downloads/release/python-31216/)

| 項目 | 待確認後的準備要求；本輪未執行 |
| --- | --- |
| 來源與建置 | 使用官方3.12.10 source release；封存來源bytes／SHA-256及取得驗證方式。使用Ubuntu archive的GCC，完整compiler／binutils／glibc修訂、configure參數、CFLAGS／LDFLAGS及binary hash另存manifest，不把系列版本當完整build |
| 固定選項 | 不啟用PGO、LTO、Py_DEBUG、BOLT、sanitizer、C profiler或自訂`-march=native`；未提供未經確認的建置命令。關PGO使首輪定義較單純，不能據此推論較快或更接近Windows |
| 安裝隔離 | 不替換系統Python；base runtime放未追蹤的研究工具位置，新Linux工作副本內建立自己的`.venv/`，不複製／共用Windows `.venv/`。Python套件只進該專案`.venv/` |
| Clock API | 保留`time.perf_counter_ns`及`time.thread_time_ns`；CPU應符合Linux目前thread計帳語義。實際implementation、可用性、整數推進、三讀間隔與擾動仍待驗；不自動fallback至process或cycles |
| 底層功能 | 後續確認thread、hashlib、sqlite3等所需stdlib extension及套件ABI；不能以source build命令成功代替入口驗收 |

選項與預設以 **v3.12.10 tag** 文件為準；目前3.12線上文件顯示3.12.16，不能冒充3.12.10建置證明。[tag建置文件](https://raw.githubusercontent.com/python/cpython/v3.12.10/Doc/using/configure.rst)、[tag venv文件](https://raw.githubusercontent.com/python/cpython/v3.12.10/Doc/library/venv.rst)、[time語義](https://docs.python.org/3.12/library/time.html)

替代R2是Ubuntu系統Python3.12，R3是upstream3.12.16：前者不是已知3.12.10，後者新增patch差異。若更重視維護版本，可改選R3，但須另定method ID、source/build與適用驗收；不能在同一方案中悄悄替換。Ubuntu官方版本表只支持24.04的3.12系列，沒有保證本案patch或binary。[Ubuntu Python表](https://ubuntu.com/developers/docs/reference/availability/python/)

## 可行性分層與目前缺口

| 層次 | 現在可支持的判定 | 尚缺內容 |
| --- | --- | --- |
| 文件語義 | Linux目前thread CPU與原問題相容，可列候選 | 不是實際implementation／解析能力證明 |
| 平台取得 | P1與P2都有具體平台定義 | 使用者可用主機、權限、容量、環境版本未知；本輪未探測 |
| 建置與套件 | R1的版本與build政策可固定 | source／binary／Linux wheel實際取得與相容性未驗證；不虛構硬體需求或工時 |
| 正確性與能力 | V69原A／B／C／D條件繼續適用 | 尚無Linux A或B通過結果，亦無C／D擾動結果 |

平台／runtime文件評估已先完成並推送`6c19957`；下方接續固定接入範圍、可比矩陣及供使用者確認的完整提案。官方來源登錄保存短摘要與定位，沒有封存網頁全文。[平台評估收據](../reports/stage12/retailrocket_session_knn_v70_linux_platform_review_20261116.json)

| 本輪小步驟 | 狀態 |
| --- | --- |
| 平台／runtime官方依據與候選方案 | 14份官方來源、7個本機來源描述已核對；平台與runtime獨立靜態審閱通過 |
| 最小接入、可比限制與確認範圍 | 下列提案已固定且獨立靜態審閱通過，待使用者確認；未準備工具／案例 |
| 環境探測／安裝／工具與案例／量測／C／D／原48筆 | 全部0 |

## 最小接入範圍：兩層準備，保持原入口行為

本節是**確認後才可準備的內容清單**，沒有新增程式、fixture或可執行命令。先核對readers與判定，再接真正typed worker的合成入口；不能只完成第一層便宣稱完整A或進入B。

| 範圍 | 靜態依據與擬保留內容 | 需要另版準備及後續驗收 |
| --- | --- | --- |
| S0 wall／CPU核心 | V63三讀邊界、V65純判定與V67 collector核心使用標準庫；reader可注入 | 新Linux manifest／來源admission，仍用`perf_counter_ns`／`thread_time_ns`，同thread guard、原始整數、有號residual、固定null槽位與原門檻；不可把新來源改標成V67 |
| S0 driver／收據 | V67 driver用`sys.executable`啟動子程序，另依賴外部Git；V65環境schema及V67 origin／reader固定 | 新plan／origin／seal／reservation／結果命名空間及Linux環境外層manifest。舊公式可沿用，舊固定schema不能硬塞新欄位；不讀寫或重置V67一次性狀態 |
| S1 真正V39／V46合成入口 | V65 fixture保留真正worker與load，依賴NumPy、psutil及stdlib SQLite，小型SQL／checkpoint檔案I/O仍存在 | 新Linux最小套件清單與artifact綁定，補Linux對應A1–16及V69七群案例；保留完整輸出、帳本、SQL／lazy fetch／watch／fault與O無新增探針，不降成空殼worker |
| S1 OS行為 | checkpoint已有Windows及非Windows分支：後者用`fcntl.flock`、`psutil.boot_time()`；reuse身分用PID／create_time | 分別驗鎖定／解鎖、程序身分、落盤與失敗恢復。已有Linux分支不是Linux驗收結果；不能直接承接Windows通過數 |
| S1 假時鐘與真實環境存取 | fixture仍呼叫`io.environment()`與程序身分；假時計時不代表整個入口沒有環境存取 | 日後將假clock讀取、必要版本／身分取得與小型檔案I/O分開列帳；runtime／clock metadata不得在本輪偷跑。準備的新案例須明列這些邊界 |
| 來源與資料保存 | 舊driver明載本地CRLF與Git LF可能不同；新Linuxcheckout不一定具有舊本地bytes | 保留歷史descriptor，另綁新checkout原始bytes、Git commit/blob及嚴格換行關係；不得泛化正規化後宣稱相同bytes。舊封存來源不改寫 |

靜態依據：[V63邊界](../scripts/retailrocket_session_knn_wall_cpu_v63.py)、[V65判定](../scripts/retailrocket_session_knn_wall_cpu_decision_v65.py)、[V67准入](../scripts/retailrocket_session_knn_clock_capability_v67.py)、[V67 driver](../scripts/run_retailrocket_session_knn_clock_calibration_v67.py)、[typed fixture](../tests/retailrocket_session_knn_wall_cpu_typed_fixture_v65.py)、[checkpoint](../scripts/retailrocket_session_knn_checkpoint_v2.py)、[reuse](../scripts/retailrocket_session_knn_reuse_v27.py)。上述是閱讀程式所得；沒有匯入或執行它們。靜態import關係不能證明所有動態載入或Linux執行依賴均已驗過。

現有[套件鎖定檔](../requirements-lock.txt)明列NumPy2.5.4、psutil7.2.2及pywinpty3.0.5，[環境指南](LOCAL_SETUP.md)也說明它屬Windows x64／Python3.12。S0不需要整套Jupyter／建模環境；S1以NumPy2.5.4、psutil7.2.2作待核對的版本起點，另需可用SQLite extension。**本輪未查驗Linux wheel／build可取得性**；後續先形成最小依賴閉包、鎖定Linux artifact與ABI，缺件時回報方案限制，不自動換版，也不只刪pywinpty便宣稱已有Linux lock。

新Linux副本只使用公開方法來源與將來建立的合成資料；私人raw、執行狀態及下載保留Git忽略位置。原始model、正式資料、原48筆、資料庫憑證及原本機服務不在接入清單內。不移植Windows MySQL啟停／Jupyter／Dashboard整套環境。

## 與原 Windows 結果的可比矩陣

以下是研究設計限制，不是跨平台實測結果。

| 比較問題 | 可以保留／另驗 | 不可推出的結論 |
| --- | --- | --- |
| 同一研究量 | 當前thread的user＋system CPU、同程式邊界、同公式及1ms目標 | 同名Python API不等於同clock backend、解析度、精度或誤差分布 |
| 相同Python patch | R1與V67保存的3.12.10對齊 | compiler、libc、build flags、stdlib／scanstring、allocator、程序啟動及OS仍不同；不能把耗時差都歸於clock來源 |
| 合成A輸出 | 在新Linux環境驗真正V39／V46、完整輸出與行為一致性 | A通過不是時鐘能力或效能改善，也不是原固定48筆／正式模型結果 |
| 新B能力 | 日後通過只支持該runtime／平台／窗口與工具的能力篩檢 | 不能反證V67停止錯誤、保證所有Linux窗口可過，或把q當真實誤差界 |
| 未來O／D或V39／V46 | 若另獲授權，必須在同一Linux環境、同一方法與窗口內配對 | Windows與Linux不能交叉組成pair、混合分布或用單一倍率換算；P1／P2也不能混合 |
| 32／33歷史運算與等待 | V47／V48原紀錄及V68限制原樣保留 | 新Linux wall−CPU不能回填歷史Windows CPU／等待；殘差也不等於I/O、GIL或特定排程等待 |
| 完整冷入口 | 將來另固定process／filesystem／cache及初始化邊界 | Linux新process不代表儲存快取已冷；更不等於Windows原完整冷入口，不能以其結果直接採用Windows V46 |

P2／P3另有host／guest排程、記憶體回收與虛擬磁碟；P4另有cgroup條件。只記錄guest的thread CPU不能得到host替它做的全部工作。即使之後有小residual，也不能證明沒有等待；大residual不能單獨指定等待原因。P1減少某些層次，仍有OS、其他工作與硬體狀態，並非無干擾基準。

## 確認後的順序與停止線

| 次序 | 後續可準備／需滿足的條件 | 不能跳過的界線 |
| --- | --- | --- |
| 1 平台與範圍確認 | 明選P1或P2、R1或另版runtime，以及是否接受只能產生新環境證據；補可用主機／權限／保存位置資訊 | 本輪的unknown不能填成已取得；P1不可用時不自動切P2。環境安裝／建立的具體動作尚未制定或執行 |
| 2 工具與案例準備 | 只準備S0＋S1的新方法manifest、接入與合成案例；列原A1–16與七群新需求的沿用／重驗映射 | 工具／案例先更新README、封存並推main，再按獲確認的範圍驗收；不能繼承V67的123項為新通過數 |
| 3 合成驗收結果 | 必須在已選環境完成適用A，保存完整輸出與失敗；版本／來源／環境清楚 | 若先在Windows驗假邏輯，只能標為Windows準備檢查，不能叫Linux入口驗收；缺Linux依賴或身份／落盤不符即停止，不拿縮減fixture替代完整A |
| 4 新B另提計畫 | 完成適用A後，再估時並確認一次新的獨立B；沿用V69的30秒整關、q≤0.1ms、bracket p99≤0.05ms且max≤0.1ms及全部完成／停止規則 | 本次確認工具準備也不含B；V67額度已用完。C／D與原48筆另行規劃，目前不排程 |

本輪不提供建置／安裝或新B耗時的假估計，因具體主機與artifact尚未確認。30秒是未來獨立B的既定上限，不是整個建置與驗收工程的預估時間。任何新build、平台或方法修訂都須保留獨立身分與適用驗收，不用結果好壞挑選環境。

## 待確認的具體提案

建議確認組合為 **P1＋R1＋S0/S1**：原生Ubuntu Server24.04 LTS amd64、GA6.8軌道、獨立CPython3.12.10非PGO／非LTO release build，僅準備最小wall／CPU工具及真正typed worker的合成案例。若沒有可用原生主機，可明確改選 **P2＋R1＋S0/S1**；這是WSL2上的獨立研究環境，不是相同部署或無條件fallback。

此提案的確認只涵蓋下一步工具／合成案例準備；沒有將安裝、來源下載、假驗收執行或B實測混成已完成／已授權工作。下一輪應先列具體準備與封存步驟。依使用者本次「確認後再準備工具與合成案例」的要求，本輪停在可審閱提案，不先製作工具或案例。

接入與可比限制的獨立靜態審閱通過；24次來源描述核對（21個唯一檔案）、27個文件連結一致，繼承V69的五組需求逐值相同，原V62–V69檔案未更動。這些是文件與資料核對，沒有新增工具驗收結果。

目前平台資訊尚未提供，實際選擇與確認維持null／false；無測試、量測或部署結果。V46仍暫不採用，原Windows結論不變。[接入與可比限制機器規格](../reports/stage12/retailrocket_session_knn_v70_linux_integration_proposal_20261116.json)
