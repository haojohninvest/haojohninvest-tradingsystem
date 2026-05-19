# stock_pick_strategy_v0519 — 完整架構整理

> ⚠️ **重要提醒**：本策略是我們 2026-05-19 對話逐項核對後確認的「新策略」，與 `筆記.md` 中提及的 v7.2/v7.3 是 **不同策略**，請勿混淆。
> 
> **命名由來**：`stock_pick_strategy_v0519`（2026年5月19日確認版本）
> 
> **來源**：2026-05-19 對話確認（項目 1~8 逐項討論後的共識）

---

## 項目 1：前置條件（股票池初篩）— ✅ 已確認

### 結論

Scanner 在「每天 T 日」判斷每一檔股票時，計算市值的公式是：

```
市值 = T日收盤價 × T日最新可用發行股數
```

### 具體查詢方式

1. **股價**：從 `DailyPrice` 查詢 `stock_id=?, date=T` 的 `close`
2. **股數**：從 `StockSharesHistory` 查詢 `stock_id=?, date__lte=T`，取 `order_by('-date').first()` 的 `outstanding_shares`
   - 如果 T 日有股數記錄，就用 T 日的
   - 如果 T 日沒有，就往最近的前一筆找（fallback）
   - 如果完全沒有，寫 `0`（市值計算時顯示為 0，會被排除）
3. **判斷**：`市值 >= 150_000_000_000`（150億）

### 參數表格

| 項目 | 條件 | 性質 | 實作 |
|------|------|------|------|
| 市場別 | TWSE 上市 | ⚠️ 測試階段設定 | `market='twse'` |
| 排除股票 | 名稱含 `*` / `*-KY` / `*-TW` | ⚠️ 測試階段設定 | `name NOT LIKE '%*%' AND ...` |
| **市值門檻** | **>= 150 億（T日收盤價 × T日最新發行股數）** | ✅ **策略主軸** | `close * outstanding_shares >= 15_000_000_000` |

### 說明

- 市值計算使用 **T日（判斷當天）** 收盤價，非入池日 A
- 發行股數使用 DB `StockSharesHistory` 查詢 `date__lte=T`，取最近一筆
- ⚠️ 項目未來可能放寬
- `Stock.market_cap` 固定值欄位**不使用**在 Scanner 裡

---

## 項目 2：Signal Pool 入池條件 — ✅ 已確認

### 結論

每日檢查所有股票，符合以下任一條件即入 Signal Pool：

| 標誌性動作 | 定義（已修正） |
|-----------|--------------|
| **跳空缺口（Gap）** | 今日最低價 > 昨日最高價 × 1.03 |
| **長紅（Surge）** | (今日收盤價 - 昨日收盤價) / 昨日收盤價 > 7% |

### 詳細說明

1. **計價方式**：使用原始價格（不做除權息調整）
   - `昨日最高價` = `DailyPrice.high`
   - `今日最低價` = `DailyPrice.low`

2. **一魚多吃**：同一股票同一天若同時出現 Gap + Surge，只算 **一次入池**（單一入池日 A）

3. **市值門檻檢查時機**：判斷日 T 當天，股票市值必須 >= 150 億元 **才能入池**
   - 若當天市值 < 150 億，即使出現 Gap 或 Surge 也不入池

---

## 項目 3：Signal Pool 出池規則 — ✅ 已確認

### 結論

```
D = T - A（已在池子裡待了幾個交易日，D >= 0）

D = 0  → 入池當天（出現 Gap/Surge 的那天）
D = 1  → 入池後第 1 個交易日
...
D = 19 → 入池後第 19 個交易日（最後一天可以留在池內）
D = 20 → 入池後第 20 個交易日（第 21 天），當天強制移出
```

### 詳細規則

1. **在池天數**：Signal Pool 內的股票最多留 **20 個交易日**（D = 0 ~ 19）
2. **每日檢查**：在池內的每一天（D = 0 ~ 19），都會被重新檢查「情境 + R20」
3. **強制移出**：當 D = 20（第 21 天），該股票強制移出 Signal Pool
   - 移出後不再進行後續判斷（不再進入情境判斷和 R20 計算）
   - 移出後也不會自動淘汰或移出 Buy Pool，但 Buy Pool 是每日重新計算，明天自然不會出現這筆
4. **重新入池**：除非這檔股票後來又有新的標誌性動作（新的入池日 A），否則不重複檢查

---

## 項目 4：情境判斷 A/B 定義 — ✅ 已確認

### 結論

每日對 Signal Pool 內尚未出池的股票（D = 0 ~ 19）檢查情境：

| 情境 | 條件 | EMA 排列示意圖 | 結果 |
|------|------|------|------|
| **A** | EMA120 < EMA60 | 120日線在60日線下方（空頭或整理），20日線位置不限 | ✅ 進入 R20 判斷 |
| **B** | EMA120 > EMA60 **且** EMA20 > EMA60 | 120日線在60日線上方，且20日線也在60日線上方（多頭排列形成中） | ✅ 進入 R20 判斷 |
| 其他 | 不符合 A 或 B | 例如：EMA120 > EMA60 但 EMA20 < EMA60（空頭排列，20日在60日下方） | ❌ 淘汰 |

### 詳細說明

1. **情境 A 理解**：EMA120 < EMA60 代表長線趨勢偏弱，但20日線可能在上方或下方，此時只要有標誌性動作就進入 R20 判斷
2. **情境 B 理解**：EMA120 > EMA60 代表長線趨勢轉強，且 EMA20 > EMA60 代表短線也在轉強，「多頭排列形成中」
3. **不符合情況**：EMA120 > EMA60（長線強）但 EMA20 < EMA60（短線弱）→ 趨勢矛盾，淘汰
4. **EMA 資料來源**：使用 `Indicator` 資料表裡的 `ema20`、`ema60`、`ema120`（已預先計算）

---

## 項目 5：R20 動態窗口公式 — ✅ 已確認

### 結論

```
T = 判斷日（今天）
A = 入池日（標誌性動作出現那天，D = 0 的當天）
D = T - A（已在池子裡待了幾個交易日，D >= 0）

R20 = Average( Close(A - (20 - D)) ～ Close(A - 1) ) / Close(T)
```

### 區間長度變化（隨 D 增加而縮短）

| D | 起點 | 終點 | 區間天數 | 平均區間 | 說明 |
|---|------|------|---------|---------|------|
| 0 | A-20 | A-1 | 20 天 | Close(A-20) ~ Close(A-1) | 入池當天，最寬窗口 |
| 1 | A-19 | A-1 | 19 天 | Close(A-19) ~ Close(A-1) | |
| ... | ... | ... | ... | ... | |
| 18 | A-2 | A-1 | 2 天 | Close(A-2) ~ Close(A-1) | |
| 19 | A-1 | A-1 | 1 天 | Close(A-1) | 入池前最後一天，最窄窗口 |
| 20+ | — | — | 0 天 | 無法計算 | 強制出池 |

### 詳細說明

1. **Average 計算方式**：簡單算術平均（SMA），不是 EMA
2. **Close 資料來源**：使用 `DailyPrice.close`，原始價格（不做除權息調整）
3. **分母**：<mark>**<重要>** Close(T)（判斷當天收盤價），不是 Close(A)</mark>
   - 設計意圖：評估「站在今天（T日），扣抵價是否偏低」。若今天收盤價很高，但接下來要扣抵的過去 20 天價格很低 → EMA20 將持續向上
4. **終點固定**：終點永遠是 **A-1（入池前最後一個交易日）**，不會隨 D 變動
5. **起點移動**：起點 = `A - (20 - D)`，隨 D 增加而向後收縮
6. **窗口縮短意義**：自然衰減的信任機制
   - D=0：最寬（看 20 天均值）→ 最信任
   - D=19：最窄（看 A-1 單日）→ 嚴格檢查
   - D≥20：無法計算 → 強制移除
7. **特殊處理**：
   - D ≥ 20：區間無法計算（起點 >= 終點），強制跳過該股票
   - 資料不足（起點超出歷史範圍）：跳過
   - 只有在 0 <= D <= 19 且資料充足時，才計算 R20

### 設計驗證

**核心目的**：站在 T 日預判「未來 EMA20 會不會持續向上」。

- EMA20 向不向上，取決於接下來要被扣抵的價格是否偏低。
- R20 < 0.9 表示：「接下來要扣抵的過去價格均值，比現在收盤價低 10% 以上」→ 均線維持向上機率高。
- 窗口隨 D 增加而縮短：因為你每過一天，就多知道了一天的真實走勢，所以要看「還沒被扣抵的剩餘價格區間」

---

## 項目 6：R20 門檻 — ✅ 已確認

### 結論

```
R20 <= 0.9（即 90%，參數可調整）
```

### 詳細說明

1. **門檻值**：R20 <= 0.9
   - R20 < 0.9 → ✅ 進入 Buy Pool
   - R20 = 0.9 → ✅ 進入 Buy Pool（因為是「小於或等於」）
   - R20 > 0.9 → ❌ 淘汰
2. **意義**：接下來要被扣抵的過去價格均值，必須「小於或等於」今天收盤價的 90%
   - 也就是說，過去扣抵價均值比現在便宜至少 10% 或以上
   - 這樣未來 EMA20 扣掉低價後，均線會持續向上
3. **參數性質**：策略主軸之一，但可調整（未來可能優化為 0.95 或 0.85）

---

## 項目 7：Buy Pool 每日重新計算 — ✅ 已確認

### ⚠️ 重要提醒：篩股系統與模擬分開討論！

**<mark>掃描器（Scanner）和投資組合模擬（Portfolio Simulation）是兩個獨立系統，請務必分開討論，不要混淆！</mark>**

- **第一階段（現在）**：先把「篩股系統」（Signal Pool → Buy Pool）邏輯確認清楚
- **第二階段（之後）**：再討論「模擬系統」（進場價格、出場邏輯、持倉上限等）
- 項目 10~14（Portfolio 相關）暫時擱置，等 Scanner 全部確認完再討論

### 結論

1. **T 日一檔股票只會進 Buy Pool 一次**
   - 同天同股票不可能有多個 Buy Pool entry（因為 Signal Pool 已經保證同天只算一次入池）
2. **隔天 Reset，重新審核**
   - Buy Pool 是每日重新計算，不是累積的
   - 今天符合就放進來，明天不符合就不進名單
3. **同一公司不同入池日的多重 Entry**
   - Signal Pool 裡可能會有同一公司、不同入池日 A 的多筆 entry（例如 4/15 和 4/20 都有 Gap）
   - 如果這些 entry 同一天 T 都通過情境 A/B 且 R20 <= 0.9
   - **只保留最新的那一筆 Entry**（以入池日 A 最晚的為準）

### Buy Pool 組成邏輯

```
每天 T 日：
  1. 檢查所有 Signal Pool 內的股票（D = 0 ~ 19）
  2. 每個 entry 檢查：
     - 情境 A/B？
     - R20 <= 0.9？
  3. 同公司有多個 entry 通過 → 只保留 A 最新的那一筆
  4. 組成今天的 Buy Pool 名單
```

---

## 項目 8：族群 Filter 回溯天數 — ✅ 已確認

### 結論

```
該股票所屬族群，在「最近 N 個交易日」內有 is_orange = True

變數名稱：sector_orange_lookback_trading_days = 5（預設 5 個交易日）
```

### 詳細說明

1. **回溯範圍**：最近 **5 個交易日**（不含假日），不是 5 個日曆天
   - 因為 `analysis_sectordivergence` 只有交易日才有資料
   - 實作方式：查詢 `date__lte=T`，取最近 N 筆有 `is_orange=True` 的交易日
2. **變數設計**：可調參數，未來可優化改為 3、7、10 等
3. **is_orange 定義**（快速複習）：
   - 族群乖離率排名「連續 2 天」排在全市場前 5 名以內
   - 從第 2 天開始亮橘燈，直到掉出前 5 名

---

## 九、策略變數總表（Scanner 部分）

### 可調參數

| 變數名稱 | 預設值 | 單位 | 說明 | 性質 |
|---------|-------|------|------|------|
| `market` | `'twse'` | string | 市場別 | ⚠️ 測試 |
| `exclude_pattern` | `['*', '*-KY', '*-TW']` | list | 排除股票名稱模式 | ⚠️ 測試 |
| `market_cap_threshold` | `150_000_000_000` | 元 | 市值門檻（150億） | ✅ 主軸 |
| `gap_threshold` | `1.03` | 倍數 | 跳空缺口門檻：今日最低價 > 昨日最高價 × 1.03 | ✅ 主軸 |
| `surge_threshold` | `7.0` | % | 長紅門檻：漲幅 > 7% | ✅ 主軸 |
| `signal_pool_max_trading_days` | `20` | 交易日 | Signal Pool 最大在池天數（D=0~19） | ✅ 主軸 |
| `r20_threshold` | `0.9` | 比率 | R20 門檻：<= 0.9（90%） | ✅ 主軸 |
| `sector_orange_lookback_trading_days` | `5` | 交易日 | 族群橘色燈號回溯天數 | ✅ 主軸 |

### 固定參數（策略核心，通常不調）

| 參數名稱 | 固定值 | 說明 |
|---------|-------|------|
| 情境 A | `EMA120 < EMA60` | 前置分類條件 |
| 情境 B | `EMA120 > EMA60 且 EMA20 > EMA60` | 前置分類條件 |
| R20 最大值 D | `19` | D=19 時窗口只剩 1 天 |
| R20 強制出池 D | `20` | D=20 時強制移出 Signal Pool |
| R20 Average 方式 | `SMA` | 簡單算術平均 |
| R20 分母 | `Close(T)` | 判斷當天收盤價 |
| R20 終點 | `Close(A-1)` | 入池前最後一個交易日 |

### EMA diff 參數遺留問題（待決定）

| 參數名稱 | 舊版本 (v7.2/7.3) | v7 新設計 | 狀態 |
|---------|------------------|----------|------|
| `entry_ema_diff_threshold` | 3% | **已移除** | ✅ 確認移除 |
| `buy_pool_ema_diff_threshold` | 5% 或 10% | **已移除** | ✅ 確認移除 |

**結論**：v7 完全移除之前的 entry_ema_diff 和 buy_pool_ema_diff 篩選，純粹以 R20 + 情境 A/B 為核心。

---

## 項目 9：族群 Filter is_orange 定義 — ✅ 已確認

### 結論

is_orange 的定義與 main branch 的 `calc_divergence.py` 完全一致。

### 詳細說明

1. **計算來源**：`apps/analysis/management/commands/calc_divergence.py` (main branch)
2. **計算邏輯**（逐行對照）：
   ```python
   # Step 1: 排除 Market Breadth，只對族群排名
   sectors_only = [c for c in divergence.columns if c != '__MARKET_BREADTH__']
   
   # Step 2: 每天每個族群的 divergence（乖離率）由大到小排名
   rank_by_day = divergence[sectors_only].rank(axis=1, method='min', ascending=False)
   
   # Step 3: 取前 5 名
   is_top5 = (rank_by_day <= 5)
   
   # Step 4: 連續 >= n 天才亮燈（n=2）
   cond_orange = consecutive_ge_n(is_top5[sector], n=2)
   ```
3. **`consecutive_ge_n` 函數行為**：
   - 連續 2 天在前 5 名，從**第 2 天**開始 `is_orange=True`
   - 掉出前 5 名當天立即變 `False`

### 範例驗證

```
假設 IC Design 連續幾天的 divergence 排名：

日期        排名    is_top5    run_pos    is_orange
2026-04-13   3      True        1          False  (第1天進前5)
2026-04-14   2      True        2          True   (第2天，開始亮橘燈)
2026-04-15   4      True        3          True   (連續第3天)
2026-04-16   6      False       1          False  (掉出前5，熄燈)
2026-04-17   1      True        1          False  (重新進入前5，第1天)
2026-04-18   2      True        2          True   (連續第2天，再次亮橘燈)
```

### 重要提醒

**⚠️ `is_orange` 的計算來自 main branch 的 `calc_divergence.py`**
- `stock-pick-strategy` branch **只讀取** main 的 `analysis_sectordivergence` 資料表
- **不會修改 main 的程式碼**
- `stock_pick_strategy_v0519` 的 Scanner 使用 main 已建立好的快取資料表

---

## 項目 16：報表 CSV 欄位 — ✅ 已確認

### 結論

輸出 **2 種 CSV**，欄位設計如下：

### 1. Buy Pool CSV（標準名單）

```
檔案名稱：buy_pool_YYYYMMDD_YYYYMMDD.csv（起訖日期）
```

| 欄位名稱 | 資料型別 | 說明 |
|---------|---------|------|
| `date` | Date | 判斷日 T |
| `stock_code` | String | 股票代號 |
| `stock_name` | String | 股票名稱 |
| `close` | Float | T 日收盤價 |
| `volume` | BigInt | T 日成交量（股） |
| `turnover` | Float | 成交金額（億元）= close × volume / 100000000 |
| `ema20` | Float | T 日 EMA20 |
| `ema60` | Float | T 日 EMA60 |
| `ema120` | Float | T 日 EMA120 |
| `signal_type` | String | 入池原因：`'gap'` / `'surge'` |
| `entry_date` | Date | 入池日 A（Signal Pool 入池日） |
| `d` | Int | 入池後天數（D = T - A） |
| `r20` | Float | 動態窗口計算的 R20 值 |
| `scenario` | String | 情境：`'A'` / `'B'` |
| `market_cap` | BigInt | T 日市值（元） |

### 2. Sector Buy Pool CSV（族群過濾後名單）

```
檔案名稱：sector_buy_pool_YYYYMMDD_YYYYMMDD.csv（起訖日期）
```

在 Buy Pool 基礎上，增加族群背離欄位：

| 欄位名稱 | 資料型別 | 說明 |
|---------|---------|------|
| ...(以上同 Buy Pool) |  |  |
| `sector_name` | String | 所屬族群名稱 |
| `sector_orange_date` | Date | 符合條件的 is_orange = True 日期 |
| `days_since_orange` | Int | 距離最近橘燈天數（0 = 今天，1 = 昨天） |

**注意**：
- `sector_orange_date` 是在回溯天數內找到的**最近的**橘燈日期
- 族群名稱來源：`sectors_stocksector` + `sectors_sector`

### 3. 輸出範例

#### Buy Pool CSV

```csv
date,stock_code,stock_name,close,volume,turnover,ema20,ema60,ema120,signal_type,entry_date,d,r20,scenario,market_cap
2026-04-15,2454,聯發科,1790.00,12345,2.21,1750.50,1680.00,1500.00,surge,2026-04-15,0,0.955,A,2840000000000
2026-04-16,2454,聯發科,1810.00,9876,1.79,1755.00,1685.00,1505.00,gap,2026-04-16,0,0.948,A,2870000000000
2026-04-15,3008,大立光,3764.00,5678,2.14,3700.00,3650.00,3400.00,surge,2026-04-15,0,0.885,B,1500000000000
```

#### Sector Buy Pool CSV

```csv
date,stock_code,stock_name,close,...,scenario,market_cap,sector_name,sector_orange_date,days_since_orange
2026-04-15,2454,聯發科,1790.00,...,A,2840000000000,IC Design,2026-04-14,1
2026-04-15,3008,大立光,3764.00,...,B,1500000000000,光學元件,2026-04-15,0
```

### 4. 同公司多 Entry 的處理

在輸出前，同一天 T、同公司只保留 **A 最新** 的一筆（已在項目 7 確認）。

### 5. 欄位選擇原因

| 欄位 | 原因 |
|------|------|
| `date` + `entry_date` + `d` | 追蹤入池時間線 |
| `r20` | 核心篩選指標，方便回測分析 |
| `scenario` | A/B 分類，方便分組比較 |
| `signal_type` | 了解入池原因（Gap/Surge） |
| `turnover` | 流動性參考 |
| `sector_name` / `sector_orange_date` | 族群動能驗證 |

---

## 後續待確認項目（待討論）

**Scanner 部分：**
- [x] 項目 1~9：全部 ✅ 已確認
- [x] 項目 16：報表 CSV 欄位 ✅ 已確認
- [ ] 項目 17：程式碼撰寫

**Portfolio 模模擬部分（暫緩之後討論）：**
- [ ] 項目 10：Portfolio 進場價格
- [ ] 項目 11-13：Portfolio 出場邏輯
- [ ] 項目 14：Portfolio 持倉上限

**Portfolio 模擬部分（暫緩之後討論）：**
- [ ] 項目 10：Portfolio 進場價格
- [ ] 項目 11-13：Portfolio 出場邏輯
- [ ] 項目 14：Portfolio 持倉上限

**Portfolio 模模擬部分（暫緩之後討論）：**
- [ ] 項目 10：Portfolio 進場價格
- [ ] 項目 11-13：Portfolio 出場邏輯
- [ ] 項目 14：Portfolio 持倉上限
- [ ] 項目 6：R20 門檻
- [ ] 項目 7：Buy Pool 每日重新計算
- [ ] 項目 8：族群 Filter 回溯天數
- [ ] 項目 9：族群 Filter is_orange 定義
- [ ] 項目 10：Portfolio 進場價格
- [ ] 項目 11-13：Portfolio 出場邏輯
- [ ] 項目 14：Portfolio 持倉上限
- [ ] 項目 15：EMA diff 參數遺留問題
- [ ] 項目 16：報表 CSV 欄位
- [ ] 項目 17：程式碼撰寫
- [ ] 項目 6：R20 門檻
- [ ] 項目 7：Buy Pool 每日重新計算
- [ ] 項目 8：族群 Filter 回溯天數
- [ ] 項目 9：族群 Filter is_orange 定義
- [ ] 項目 10：Portfolio 進場價格
- [ ] 項目 11-13：Portfolio 出場邏輯
- [ ] 項目 14：Portfolio 持倉上限
- [ ] 項目 15：EMA diff 參數遺留問題
- [ ] 項目 16：報表 CSV 欄位
- [ ] 項目 17：程式碼撰寫
