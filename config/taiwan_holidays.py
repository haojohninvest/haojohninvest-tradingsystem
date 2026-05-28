"""
台股休市日設定
請手動填寫每年的休市日（排除週六日後的非交易日）

格式: date(YYYY, M, D)
注意: 只需列出平日(Mon-Fri)的休市日，週末會由程式自動排除

資料來源參考: 台灣證券交易所行事曆 https://www.twse.com.tw/zh/holiday/holidaySchedule
"""
from datetime import date

TAIWAN_HOLIDAYS = set()

# ==== 2022 年 ====
TAIWAN_HOLIDAYS.update([
    date(2022, 1, 31),
    date(2022, 2, 1),
    date(2022, 2, 2),
    date(2022, 2, 3),
    date(2022, 2, 4),
    date(2022, 2, 28),
    date(2022, 4, 4),
    date(2022, 4, 5),
    date(2022, 5, 2),
    date(2022, 6, 3),
    date(2022, 9, 9),
    date(2022, 10, 10),
])

# ==== 2023 年 ====
TAIWAN_HOLIDAYS.update([
    date(2023, 1, 2),
    date(2023, 1, 20),
    date(2023, 1, 23),
    date(2023, 1, 24),
    date(2023, 1, 25),
    date(2023, 1, 26),
    date(2023, 1, 27),
    date(2023, 2, 27),
    date(2023, 2, 28),
    date(2023, 4, 3),
    date(2023, 4, 4),
    date(2023, 4, 5),
    date(2023, 5, 1),
    date(2023, 6, 22),
    date(2023, 6, 23),
    date(2023, 9, 29),
    date(2023, 10, 9),
    date(2023, 10, 10),
])

# ==== 2024 年 ====
TAIWAN_HOLIDAYS.update([
    date(2024, 1, 1),
    date(2024, 2, 8),
    date(2024, 2, 9),
    date(2024, 2, 12),
    date(2024, 2, 13),
    date(2024, 2, 14),
    date(2024, 2, 28),
    date(2024, 4, 4),
    date(2024, 4, 5),
    date(2024, 5, 1),
    date(2024, 6, 10),
    date(2024, 9, 17),
    date(2024, 10, 10),
])

# ==== 2025 年 ====
TAIWAN_HOLIDAYS.update([
    date(2025, 1, 1),
    date(2025, 1, 27),
    date(2025, 1, 28),
    date(2025, 1, 29),
    date(2025, 1, 30),
    date(2025, 1, 31),
    date(2025, 2, 28),
    date(2025, 4, 3),
    date(2025, 4, 4),
    date(2025, 5, 1),
    date(2025, 5, 30),
    date(2025, 10, 10),
])

# ==== 2026 年 (已公布部分) ====
TAIWAN_HOLIDAYS.update([
    date(2026, 1, 1),
    date(2026, 2, 16),
    date(2026, 2, 17),
    date(2026, 2, 18),
    date(2026, 2, 19),
    date(2026, 2, 20),
    date(2026, 4, 3),
    date(2026, 4, 6),
    date(2026, 5, 1),
    date(2026, 6, 19),
    date(2026, 9, 25),
    date(2026, 9, 28),
    date(2026, 10, 9),
])


def is_holiday(check_date):
    """檢查是否為台股休市日（僅手動設定的休市日，週末由呼叫端自行處理）"""
    return check_date in TAIWAN_HOLIDAYS
