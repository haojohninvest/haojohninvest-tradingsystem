# 豪強資本交易系統 - 資料重建計畫書

> 版本：v1.0  
> 日期：2026-05-20  
> 目標：修正爬蟲 + 確保 2020-01-01 ~ 2026-05-20 股價資料正確

---

## ⏱️ 總時程概覽

| 階段 | 任務 | 預估時間 | 是否需人工確認 |
|------|------|---------|-------------|
| Phase 0 | 備份 db.sqlite3 | 5 分鐘 | ✅ 是 |
| Phase 1 | 修正爬蟲程式碼（週末檢查 + 欄位索引） | 1~2 小時 | ✅ 是（code review） |
| Phase 2 | 刪除週末髒資料（43,399 筆） | 2 分鐘 | ⚠️ 可選確認 |
| Phase 3 | 清空 2020~today 的 DailyPrice | 2 分鐘 | ✅ 是（不可逆） |
| Phase 3 | 重新爬取 2020~today（~1500 交易日） | **3~5 天** | ❌ 自動（nohup） |
| Phase 4 | 重算 calc_indicators --full | **1~2 天** | ❌ 自動 |
| Phase 4 | 重算 calc_market_breadth --full | **數小時~1 天** | ❌ 自動 |
| Phase 4 | 重算 calc_divergence | **數小時~1 天** | ❌ 自動 |
| Phase 5 | 驗證抽樣比對 | 2~4 小時 | ✅ 是 |
| **總計** | | **5~10 天** | |

**注意**：Phase 3~4 可全自動背景執行，您不需要盯著。但 Phase 0、1、5 需要您確認或參與。

---

## Phase 0: 備份（5 分鐘）

### 執行指令
```bash
cp ~/haojohninvest-tradingsystem/db.sqlite3 \
   ~/haojohninvest-tradingsystem/db.sqlite3.backup.20260520_full
ls -lh ~/haojohninvest-tradingsystem/db.sqlite3.backup.20260520_full
```

### 驗證
- 確認備份檔大小 > 100MB
- 確認備份日期正確

### 回滾方案
- 若任何後續步驟出問題，隨時可用 `cp db.sqlite3.backup.20260520_full db.sqlite3` 恢復

---

## Phase 1: 修正爬蟲（1~2 小時，含測試）

### Step 1A: 修正 run_crawler.py --date 週末檢查（10 分鐘）

**修改檔案**：`apps/market_data/management/commands/run_crawler.py`

```python
# 現有 code（line 31-34）
elif options.get('date'):
    target_date = datetime.strptime(options['date'], '%Y-%m-%d').date()
    self.stdout.write(f"正在處理 {target_date}...")
    MarketCrawler.run_daily_crawl(target_date)
```

**修改為**：
```python
elif options.get('date'):
    target_date = datetime.strptime(options['date'], '%Y-%m-%d').date()
    # PATCH: 增加週末檢查
    if target_date.weekday() >= 5:
        self.stdout.write(
            self.style.WARNING(
                f"指定日期 {target_date} 為週六/日，台股休市，跳過爬取。"
            )
        )
        return
    self.stdout.write(f"正在處理 {target_date}...")
    MarketCrawler.run_daily_crawl(target_date)
```

### Step 1B: 修正 crawler.py 改用欄位索引（1~1.5 小時）

**修改檔案**：`apps/market_data/crawler.py`

**根因**：證交所 CSV 在除權息日會多一個「除權息參考價」欄位，導致中文欄位名稱對齊錯誤。

**方案**：
- TWSE：先找到 header 行，用**欄位索引**（第 0=代號, 第 2=成交股數, 第 3=成交金額, 第 4=開盤, 第 5=最高, 第 6=最低, 第 7=收盤...）定位
- 不再依賴中文欄位名稱
- 同樣方式處理 OTC

**驗證**：
- 手動執行 `python manage.py run_crawler --date 2024-05-20`（除權息日），確認收盤價與 API 一致

---

## Phase 2: 刪除週末髒資料（2 分鐘）

### 執行指令
```bash
cd ~/haojohninvest-tradingsystem
source venv/bin/activate
python manage.py shell -c "from apps.market_data.models import DailyPrice; deleted = DailyPrice.objects.filter(date__week_day__in=[1,7]).delete(); print(f'Deleted weekend records: {deleted[0]}')"
```

### 預期結果
- 刪除 43,399 筆週末資料
- 不影響平日資料

### 驗證
```bash
python -c "from apps.market_data.models import DailyPrice; print('Remaining weekend:', DailyPrice.objects.filter(date__week_day__in=[1,7]).count())"
```
應該顯示 0

---

## Phase 3: 清空並重建 2020~today DailyPrice（3~5 天，自動化）

### Step 3A: 清空 2020~today 的 DailyPrice（2 分鐘）

```bash
python manage.py shell -c "from apps.market_data.models import DailyPrice; deleted = DailyPrice.objects.filter(date__gte='2020-01-01').delete(); print(f'Deleted 2020~today: {deleted[0]}')"
```

### Step 3B: 分批爬取 2020~today（3~5 天，自動化）

**策略**：不一次執行 `--start_date 2020-01-01`（會跑 1500 天，timeout 風險），改為**每 3 個月一批**：

```bash
# 批次腳本 rebuild_prices.sh
#!/bin/bash
cd ~/haojohninvest-tradingsystem
source venv/bin/activate

for year in 2020 2021 2022 2023 2024 2025 2026; do
    for month_start in 01-01 04-01 07-01 10-01; do
        start="${year}-${month_start}"
        python manage.py run_crawler --start_date "$start"
        sleep 10
    done
done
```

**估算**：
- 每季約 60 交易日，每次約 5 分鐘
- 28 批次 × 5 分鐘 = **約 2.5 小時**
- 但證交所有 rate limit（每季可能 delay 30 秒）
- 保守估計：**3~5 天**

**啟動方式**：
```bash
nohup ./rebuild_prices.sh > logs/rebuild_prices.log 2>&1 &
```

---

## Phase 4: 重算所有技術指標（2~4 天，自動化）

### Step 4A: calc_indicators --full（1~2 天）

```bash
nohup python manage.py calc_indicators --full > logs/calc_indicators_full.log 2>&1 &
```

### Step 4B: calc_market_breadth --full（數小時~1 天）

```bash
nohup python manage.py calc_market_breadth --full > logs/calc_breadth_full.log 2>&1 &
```

### Step 4C: calc_divergence（數小時~1 天）

```bash
nohup python manage.py calc_divergence > logs/calc_divergence_full.log 2>&1 &
```

**執行順序**：等待 4A 完成後再執行 4B 和 4C（因為 Market Breadth 依賴 Indicator）

---

## Phase 5: 驗證（2~4 小時）

### 驗證清單

| 項目 | 方法 | 通過標準 |
|------|------|---------|
| 週末無資料 | `DailyPrice.objects.filter(date__week_day__in=[1,7]).count() == 0` | ✅ 0 |
| 除權息日正確 | 用手動抽查 2024-05-20、2025/08/12 等 | ✅ 與證交所 API 一致 |
| 指標合理 | EMA20、EMA60 不得為 None 過多 | ✅ < 5% 為 None |
| Market Breadth 合理 | breadth_percent 介於 0~100 | ✅ 全部在範圍內 |
| 選股策略輸出 | 跑一遍策略，看是否有異常 | ✅ 無異常 |

---

## 風險與因應

| 風險 | 機率 | 影響 | 因應 |
|------|------|------|------|
| 證交所 API 在爬取期間被封 IP | 中 | 爬取中斷 | 增加 sleep 到 5~10 秒，分批執行 |
| 重建期間需要查詢歷史資料 | 高 | 使用者無法查詢 | **重建期間網站可瀏覽，但歷史資料不完整，需公告** |
| calc_indicators --full 超時 | 高 | 指標重建失敗 | 改用 days=100 分批執行 |
| 重建後仍有少量錯誤 | 低 | 資料不完整 | Phase 5 驗證時發現，再手動補爬 |

---

## 使用者需確認的事項

1. **是否同意本計畫？**
2. **是否現在開始 Phase 0（備份）？**
3. **重建期間（3~5 天），網站是否需要暫停「策略選股」功能？**（建議暫停，因為歷史資料不完整）
4. **是否有特定日期需要優先驗證？**（例如最近的 2026/05 是否有重大交易決策）
5. **備份後，是否接受「清空 2020~today DailyPrice」？**

---

## 執行指令表（待確認後一鍵執行）

```bash
# === Phase 0: 備份 ===
cp ~/haojohninvest-tradingsystem/db.sqlite3 ~/haojohninvest-tradingsystem/db.sqlite3.backup.20260520_full

# === Phase 1: 啟動 Scheduler（已啟動，會在重建期間自動抓最新資料）===
# Scheduler 已經在跑了，不需要重啟

# === Phase 2: 刪除週末資料 ===
cd ~/haojohninvest-tradingsystem && source venv/bin/activate
python manage.py shell -c "from apps.market_data.models import DailyPrice; DailyPrice.objects.filter(date__week_day__in=[1,7]).delete(); print('Weekend data deleted')"

# === Phase 3A: 清空 2020~today DailyPrice ===
python manage.py shell -c "from apps.market_data.models import DailyPrice; DailyPrice.objects.filter(date__gte='2020-01-01').delete(); print('2020~today cleared')"

# === Phase 3B: 分批爬取 ===
# 將自動生成 rebuild_prices.sh 並執行

# === Phase 4A~C: 重算指標 ===
# 將在爬取完成後自動執行

# === Phase 5: 驗證 ===
# 將在指標重算完成後執行
```

---

**請確認以上計畫後，我們開始執行。**
