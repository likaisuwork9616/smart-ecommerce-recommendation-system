# Stage 12 V46 字元檢查優化候選

V45 的低頻抽樣顯示字元檢查在八對都比 `scanstring` 慢。V46 用編譯後的正規表示式找到下一個特殊字元，讓一般字元在搜尋中跳過 Python 逐字迴圈。遇到反斜線、控制字元和 surrogate 時，候選依原規則接受或拒絕。遇到結尾引號後仍由原 `scanstring` 產生字串並核對結束位置。候選由研究工具單獨載入。

| 項目 | 驗證或比較方式 |
| --- | --- |
| 字串值與拒絕規則 | Unicode 邊界、非零起點、32 個控制字元、短 escape、大小寫長 escape、截斷及多個錯誤先後順序，逐案比較輸出、例外型別與訊息 |
| 混合資料 | 4,096 個固定種子的字串案例與 V39 比對 |
| 完整解碼 | 比對有效 bytes、非法 UTF-8、錯誤標點、額外內容與輸入型別。深度 1,600 的陣列逐層核對 tuple |
| 測試結果 | 7 項新測試與 21 項 V39 回歸測試全通。已核對 V45 封存的同一份 4,566,194 bytes model canonical |
| 計時設計 | 原版和候選各一暖機，八對交替執行。只讀取整次 `_decode` 的開始與結束時間，計時外核對完整 tuple 結構與編碼深度 |

```powershell
.venv/Scripts/python.exe -B -m unittest -v tests.test_retailrocket_session_knn_string_v46 tests.test_retailrocket_session_knn_typed_v39
.venv/Scripts/python.exe -B -m scripts.compare_retailrocket_session_knn_string_v46 --measure
```
