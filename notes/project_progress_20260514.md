# 豪強資本交易系統 — 專案進度筆記

> 更新時間：2026-05-14（台北時間）
> 作者：AI 助理（Johnny 的 coding agent）

---

## 一、專案目標

建立一個台股交易系統，包含：
- ✅ 每日自動抓台股上市/上櫃價格
- ✅ 大盤 Market Breadth 圖表
- ✅ 族群背離圖表（族群圖）
- ✅ 線上後台可手動修改
- ✅ 背景自動排程，無需 Johnny 每天手動操作

---

## 二、已完成項目（按順序）

### Phase 1: 資料修復與模型建立

1. **修正上櫃爬蟲抓取欄位順序** 
   - 修改檔案：`apps/market_data/crawler.py`
   - 問題：OTC（上櫃）的收盤價和漲跌欄位搞混了
   - 結果：修正為 `close, change, open, high, low`

2. **新增季度股本模型**
   - 新增檔案：`apps/market_data/management/commands/fetch_finmind_shares.py`
   - 新增模型：`StockSharesHistory`（放在 `market_data/models.py` 裡面）
   - 用途：從 FinMind 抓每季公開發行股數，取代單一 `stock.outstanding_shares` 欄位
   - 決定：用「季度股本」計算歷史市值，比用單一數字更準確
   - 注意：`Stock.outstanding_shares` 仍保留，但已不被 `calc_divergence` 使用

3. **建立背景回填腳本**
   - 新增檔案：`apps/market_data/management/commands/backfill_runner.py`
   - 特性：支援斷點續傳（`.backfill_progress.json`），每次重跑會從上次失敗處繼續
   - 決定：回填 2016-01-04 到 2026-05-11 的所有上市/上櫃日線資料

### Phase 2: EC2 初始化

4. **EC2 環境準備**
   - 主機：`t3.small`，Ubuntu 24.04
   - IP：`16.176.34.16`
   - 安裝 Python 3.12、建立 venv、安裝 requirements.txt
   - 初始化 Django：`migrate`、`createsuperuser`
   - 撰寫 `.env` 檔，填入 `FINMIND_TOKEN`

5. **啟動排程腳本**
   - 建立 systemd service：`haoqiang-scheduler`
   - 用途：每天用 `auto_pipeline.sh` 自動跑背景任務

6. **抓取單日 Stock 表**
   - 指令：`python manage.py fetch_daily 2026-05-08`
   - 結果：產生 1,962 筆股票基本資料（上市 + 上櫃）

### Phase 3: 大量回填（2016 → 2026）

7. **FinMind 季度股本抓取**
   - 指令：`fetch_finmind_shares`
   - 結果：8,003 筆 `StockSharesHistory` 記錄
   - 速率限制：FinMind free plan B，600 req/hour

8. **背景回填 DailyPrice**
   - 指令：`backfill_runner`（分批跑，避開 API 上限）
   - 結果：4,357,293 筆 `DailyPrice`（2016-01-04 ~ 2026-05-11）

9. **健康檢查調整**
   - 修改檔案：`check_stock_health.py`
   - 放寬缺失股票警報閾值（原本太嚴格會一直報警）
   - 目前設定：超過 300 檔缺失才警報，或只檢查市值前 500

### Phase 4: 修正技術指標

10. **移除 `five_day_return`**
    - 修改檔案：`apps/market_data/indicators.py`、`apps/analysis/models.py`
    - 原因：`calc_divergence` 不需要這個欄位
    - 已跑過 migration：`0003_remove_indicator_five_day_return`

11. **改 Market Breadth 為 EMA20**
    - 修改檔案：`calc_divergence.py`
    - 原本：用 SMA20（簡單移動平均）
    - 現在：用 EMA20（指數移動平均），對近期價格更敏感
    - 判斷「收盤是否站上均線」時也改看 EMA20

12. **改市值公式**
    - 修改檔案：`calc_divergence.py`
    - 原本：直接用 `stock.outstanding_shares`
    - 現在：查 `StockSharesHistory`，依日期找到最近的季度股本
    - Fallback：如果找不到當季，用上一季；再找不到寫 0

### Phase 5: 部署網站

13. **安裝 Gunicorn + 收集靜態檔**
    - 靜態檔輸出到：`static_collected/`（131 個檔案）

14. **建立 systemd service**
    - 服務名：`haoqiang-gunicorn`
    - Binding：Unix socket `/tmp/gunicorn.sock`

15. **安裝與設定 Nginx**
    - 反向代理：`port 80` → `/tmp/gunicorn.sock`
    - 靜態檔路徑：`/static/`

16. **AWS Security Group**
    - 新增 inbound rule：允許 `port 80`（IPv4 anywhere）

17. **網站上線**
    - 網址：http://16.176.34.16
    - 目前狀態：可以開啟，但圖表區顯示「無資料」（因為 `calc_indicators` 和 `calc_divergence` 還沒跑完）

---

## 三、正在進行中

### calc_indicators 運算中（估算 20–40 分鐘）
- **狀態**：已於 ~2026-05-14 11:00（台北時間）啟動
- **進度**：EC2 CPU 接近 100%（確認中）
- **輸入**：4,357,293 筆 `DailyPrice` + 8,003 筆 `StockSharesHistory`
- **輸出**：`Indicator` 快取表（預計 ~4M 筆）
- **計算內容**：每支股票每天的 SMA20、EMA20、RSI20、乖離率等

### calc_divergence（尚未啟動，等 calc_indicators 完成）
- **輸入**：所有 `Indicator` + `DailyPrice` + `StockSector`
- **輸出**：`SectorDivergence` 快取表
- **圖表**：族群背離爭霸戰、大盤寬度、族群詳情

---

## 四、EC2 當前狀態

| 項目 | 狀態 |
|------|------|
| EC2 Instance | Running（t3.small） |
| OS | Ubuntu 24.04 |
| IP | 16.176.34.16 |
| SSH | 目前連不上（CPU 滿載中） |
| Django | Running（Gunicorn + Nginx） |
| DailyPrice 筆數 | 4,357,293 |
| StockSharesHistory 筆數 | 8,003 |
| Indicator 筆數 | 0（計算中） |
| SectorDivergence 筆數 | 0（還沒跑） |

---

## 五、重要設計決定（為什麼這樣做）

| 決定 | 理由 |
|------|------|
| 用 EC2（不是 Railway/Render）| Johnny 希望可以隨時改 code，有完全控制權 |
| SQLite（不是 PostgreSQL）| 初期簡單，不用額外設定連線 |
| 用季度股本 `StockSharesHistory` | 歷史市值不能只用「現在的股本」，要看對應日期附近的 |
| 回填從 2016 開始 | 確保 Market Breadth 和 EMA20/RSI20 的指標值在跑第一段就有 20 天資料，不會失真 |
| 族群分類用 Excel 匯入 | 台灣沒有免費的 open API 自動分類，用手動 Excel 最可控 |
| Market Breadth 看市值前 200 | 排除小型股票干擾，只看真正有影響力的 |
| 橘燈 = 連續 2 天排名前 5 | 過濾掉一時強勢的雜訊，只看「持續強」 |
| 紫燈 = 由負轉正 | 抓「族群剛睡醒」的轉折點，有前置指標意義 |
| 不檢查假日 | 讓 crawler 每天跑，假日沒資料就跳過，省下維護假日表的麻煩 |

---

## 六、檔案清單（本機改動過的）

```
apps/market_data/crawler.py                  ← 修正 OTC 欄位順序
apps/market_data/models.py                   ← 新增 StockSharesHistory
apps/market_data/indicators.py               ← 移除 five_day_return
apps/market_data/management/commands/
  fetch_finmind_shares.py                    ← 新增：抓季度股本
  backfill_runner.py                         ← 新增：回填 2016-2026
  check_stock_health.py                      ← 放寬警報閾值
apps/analysis/management/commands/
  calc_divergence.py                         ← 改 EMA20 + StockSharesHistory
apps/analysis/models.py                      ← 移除 five_day_return
apps/sectors/models.py                       ← Sector + StockSector
apps/sectors/management/commands/
  import_sectors.py                          ← 從 Excel 匯入族群
config/settings.py                           ← 讀 DJANGO_ALLOWED_HOSTS
.env                                         ← FINMIND_TOKEN, DEBUG=False
haoqiang-gunicorn.service                     ← systemd 設定
nginx config                                 ← reverse proxy
```

---

## 七、待辦事項（Next Steps）

- [x] 等 `calc_indicators` 跑完
- [x] 確認 SSH 恢復連線
- [x] 在 EC2 上跑 `python manage.py calc_divergence`
- [x] 驗證網站圖表正確顯示
- [x] 更新 `views.py` 改用 `StockSharesHistory`
- [x] 新增 `.gitignore` 保護 `db.sqlite3`
- [ ] 測試市值排行頁面是否正常
- [ ] 長期優化：把 `StockSharesHistory` 查詢改成 raw SQL 或快取字典

---

## 七之一、本日問題與教訓紀錄（重要！）

### 問題 1：`db.sqlite3` 被 git 覆蓋導致資料全失
**原因**：本地 git add -A 時不小心把 `db.sqlite3` stage 進去，EC2 pull 時覆蓋了 449MB 的實際資料庫，變成空白 284KB 檔案。
**解法**：新增 `.gitignore` 排除 `db.sqlite3` 和 `logs/`。**絕對不能把資料庫放進 git！**

### 問題 2：`market_breadth_view` 載入 430 萬筆導致 OOM
**原因**：`views.py` 原本用 `DailyPrice.objects.all()` 讀取全部歷史資料，2GB RAM 不夠用，worker 被 kill。
**解法**：改為 `filter(date__gte=cutoff)` 只讀最近 150 天。

### 問題 3：`StockSharesHistory` 2000 次迴圈查詢導致 504 timeout
**原因**：對每支股票單獨查一次 `StockSharesHistory.objects.filter(...).first()`，2000 次 DB round-trip 超過 30 秒。
**解法**：改為一次性查詢全部 `StockSharesHistory`，用 Python dict 映射，速度從 30 秒降到 <1 秒。

### 問題 4：改 views.py 時漏 import `StockSharesHistory`
**原因**：編輯時只改了使用處，忘了改 import 行。
**解法**：永遠記得 `from apps.market_data.models import ..., StockSharesHistory`

### 問題 5：系統切換到 plan mode 導致「不回應」
**原因**：AI 系統有時會自動進入 read-only 的 plan mode，看起來像突然消失。
**解法**：不是我的錯，是系統限制。通常等一下就會恢復 build mode。

### 總結教訓
1. **永遠檢查 `.gitignore`** 再執行 `git add -A`
2. **永遠確認 import 完整性** 再 push
3. **批量查詢 > 迴圈單筆查詢**（N+1 問題）
4. **測試時先看 error log** 再猜測問題

---

## 八、如果遇到問題怎麼辦

| 問題 | 解法 |
|------|------|
| SSH 連不上 | 去 AWS Console → Monitoring 看 CPU，接近 100% 就等；持續 1hr+ 就 Reboot |
| 網站打不開 | 檢查 EC2 安全群組 port 80 是否還在 |
| `calc_indicators` 跑太慢 | t3.small 只有 2 vCPU + 2GB RAM，可考慮升級到 t3.medium |
| FinMind API 超限 | free plan B 只有 600 req/hour，超過會被鎖；目前抓股本時已分段避免 |
| 圖表沒資料 | 確認 `Indicator` 和 `SectorDivergence` 資料表有筆數；沒有就是 calc 還沒跑完 |
| 想手動觸發計算 | SSH 到 EC2，進 venv，跑 `python manage.py calc_indicators` 即可 |

---

## 九、族群圖完整流程（白話版）

```
Excel 產業分類
    ↓
import_sectors.py 匯入到 Sector + StockSector
    ↓
每天執行 calc_divergence.py：
  DailyPrice  ×  StockSector  ×  StockSharesHistory（依日期匹配股本）
    ↓
每族群的總市值 → EMA20 → 乖離率 = (今日市值 - EMA20) / EMA20
    ↓
比較各族群乖離率，標註橘燈（連續 2 天前 5）/ 紫燈（由負轉正）
    ↓
結果存入 SectorDivergence（快取表，每次計算先清空舊資料）
    ↓
網站開 /analysis/divergence/
    ↓
讀 SectorDivergence 快取表，只取最近 150 天、前 30 名族群
    ↓
Plotly 畫成橫向長條圖，每個族群一個 panel
    ↓
大盤 Market Breadth 放在最左邊（綠→紅表示過熱到過冷）
```

---

## 十、備註

- 本筆記位於 `notes/project_progress_20260514.md`
- 未來更新請繼續追加新筆記或覆蓋此檔
- 有任何決定或修改都要記錄下來，方便 Johnny 自己日後回顧
