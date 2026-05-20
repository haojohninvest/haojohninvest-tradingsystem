# 重建計畫：2023~today 股價資料 + 三層檢驗機制

> 版本：v1.0 | 日期：2026-05-20 | 預估時間：**3~4 天全自動**

---

## 為什麼需要檢驗機制？

| 風險 | 後果 |
|------|------|
| 爬取 3 天後突然發現某天錯誤 | 必須全部重來 |
| 除權息日欄位偏移沒發現 | 策略選股誤導交易 |
| 證交所 API 偶爾回傳空資料 | 當天股票全缺 |
| 網路中斷導致批次中斷 | 不知從哪裡續傳 |

**沒有檢驗 = 做完也不知道對不對。**

---

## 三層檢驗機制設計

### Layer 1：即時檢驗（爬取當下完成 ✅）

**每筆價格寫入前檢查：**
```python
class PriceValidator:
    @staticmethod
    def validate(price_row, prev_close=None):
        # 1. 基本合理性
        if price_row['close'] <= 0: return False, "close <= 0"
        if price_row['low'] > price_row['high']: return False, "low > high"
        if not (price_row['low'] <= price_row['close'] <= price_row['high']):
            return False, "close not in [low, high]"
        
        # 2. 異常跳動（與前日比較）
        if prev_close and abs(price_row['close'] - prev_close) / prev_close > 0.5:
            return False, f"jump > 50% ({prev_close} -> {price_row['close']})"
        
        # 3. 漲跌幅限制（台股 ±10%，創新板 ±15%）
        if prev_close:
            change = (price_row['close'] - prev_close) / prev_close
            if abs(change) > 0.15:
                return False, f"change > 15% ({change:.1%})"
        
        return True, "OK"
```

**結果：** 不合法價格立刻被擋下，不寫入 DB

---

### Layer 2：批次檢驗（每晚自動執行 ✅）

**每天爬取結束後（或每季跑完後）：**
```python
def batch_validate(date_str):
    # 1. 當日必須是交易日（查交易日曆 API）
    if not is_trading_day(date_str):
        return False, "Not a trading day"
    
    # 2. 檢查當日筆數（台股上市+上櫃約 1700~1800 筆）
    count = DailyPrice.objects.filter(date=date_str).count()
    if count < 1500:
        return False, f"Only {count} records (< 1500)"
    
    # 3. 抽樣 10 筆與證交所 API 比對
    sample = DailyPrice.objects.filter(date=date_str).order_by('?')[:10]
    for p in sample:
        api_close = fetch_twse_single(p.stock.code, date_str)
        if abs(p.close - api_close) > 0.01:
            return False, f"{p.stock.code} mismatch: DB={p.close}, API={api_close}"
    
    return True, "All checks passed"
```

**結果：** 若失敗，當天批次標記為「待重爬」，不自動進入下一步

---

### Layer 3：全量驗證（重建完成後 🔍）

**全部爬完後執行：**
```python
def final_validate():
    # 1. 週末無資料
    weekend_count = DailyPrice.objects.filter(date__week_day__in=[1,7]).count()
    assert weekend_count == 0, f"Found {weekend_count} weekend records!"
    
    # 2. 每季抽樣 3 天，各抽 10 支股票與 API 比對
    for quarter_start in ['2023-01-02', '2023-04-03', '2023-07-03', ..., '2026-04-01']:
        # 驗證...
        pass
    
    # 3. 連續性檢查：不能有連續 3 天以上缺資料的交易日
    # 4. 生成驗證報告
```

**結果：** 產生一份 `VALIDATION_REPORT_2023.md`，列出所有異常

---

## 修改內容一覽

| 檔案 | 修改內容 | 時間 |
|------|---------|------|
| `apps/market_data/crawler.py` | 新增 `PriceValidator` + 改用欄位索引 | 1 小時 |
| `apps/market_data/management/commands/run_crawler.py` | `--date` 週末檢查 | 10 分鐘 |
| `apps/market_data/validators.py` | 新增檢驗類別（日曆、筆數、API 比對） | 30 分鐘 |
| `scripts/rebuild_2023.sh` | 重建批次腳本（含即時 stop-on-error） | 20 分鐘 |
| `scripts/validate_batch.py` | 批次檢驗腳本 | 30 分鐘 |

---

## 重建時程 2023~today（3~4 天）

| Day | 上午 | 下午 | 晚上 |
|-----|------|------|------|
| **Day 1** | Phase 0 備份 + Phase 1 修正爬蟲 | Phase 2 清空 2023~today | Phase 3 開始爬取 2023Q1 |
| **Day 2** | 爬取 2023Q2+Q3（自動） | 爬取 2023Q4+2024Q1（自動） | Layer 2 批次檢驗 Day 1~2 |
| **Day 3** | 爬取 2024Q2+Q3+Q4（自動） | 爬取 2025Q1+Q2（自動） | Layer 2 批次檢驗 Day 3 |
| **Day 4** | 爬取 2025Q3+Q4+2026Q1（自動） | Phase 4 重算 indicators | Phase 5 全量驗證 + 報告 |

---

## 您現在要決定

1. **是否同意這份計畫？**
2. **是否現在開始 Phase 0（備份）？**
3. **檢驗機制是否需要新增「郵件/Line 通知」？**（批次失敗時通知您）

**請確認後，我立即開始執行。**