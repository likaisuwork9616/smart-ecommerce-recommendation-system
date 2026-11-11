# Stage 12 V43 Model 解碼分項

V42 的 model `_decode` 中位數為 1.841055 秒。V43 以同一份 4,566,194 bytes 的 model canonical 重播原 V39 解碼器。每次在計時外比對完整 tuple 結構與編碼深度。V42 的來源與方法描述符和 model canonical SHA-256 已在實測前核對。

| 分項 | 計時邊界 |
| --- | --- |
| 字串掃描 | 累加每次原 `_string` 執行時間，包括 escape 檢查與 `scanstring` 建立字串 |
| Tuple 建置 | 累加每次 `tuple` 把已收集的陣列元素轉成 tuple 的時間 |
| UTF-8 解碼 | 計時原本一次 `bytes.decode('utf-8')` |
| 陣列解析與迴圈 | 整段 `_decode` 扣除上述三項。包括讀取標記、堆疊操作、元素加入父陣列及計時器留在迴圈內的開銷 |

原版與加計時版各暖機一次，接著交替跑六對。分項取自加計時版，六對完整時間用來觀察加計時後的差距。原版的 token tree 另用來核對每次觀測的字串與 tuple 呼叫數。

4 項人工測試已通過，涵蓋原版與加計時版的完整輸出一致性、已知呼叫數、原有錯誤拒絕，以及計時扣除與配對順序的驗證。

```powershell
.venv/Scripts/python.exe -B -m unittest -v tests.test_retailrocket_session_knn_decode_v43
.venv/Scripts/python.exe -B -m scripts.diagnose_retailrocket_session_knn_decode_v43 --measure
```
