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

目前只完成平台／runtime文件評估；接著固定接入範圍、可比矩陣及供使用者確認的完整提案。官方來源登錄保存短摘要與定位，沒有封存網頁全文。[平台評估收據](../reports/stage12/retailrocket_session_knn_v70_linux_platform_review_20261116.json)

| 本輪小步驟 | 狀態 |
| --- | --- |
| 平台／runtime官方依據與候選方案 | 14份官方來源、7個本機來源描述已核對；平台與runtime獨立靜態審閱通過 |
| 最小接入、可比限制與確認範圍 | 接著固定 |
| 環境探測／安裝／工具與案例／量測／C／D／原48筆 | 全部0 |
