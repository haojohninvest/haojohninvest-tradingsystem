import pandas as pd
from datetime import date, timedelta
import logging

logger = logging.getLogger(__name__)


class PriceValidator:
    """
    三層檢驗機制中的 Layer 1: 即時檢驗
    每筆價格寫入 DB 前執行
    """
    
    @staticmethod
    def validate_row(row, prev_close=None):
        """
        驗證單筆價格資料是否合理
        
        Args:
            row: dict with keys 'open', 'high', 'low', 'close', 'volume'
            prev_close: 前一日收盤價（可選）
        
        Returns:
            (is_valid: bool, reason: str)
        """
        # 1. 基本合理性
        if pd.isna(row.get('close')) or row['close'] <= 0:
            return False, f"close <= 0 or NaN: {row.get('close')}"
        
        if pd.isna(row.get('volume')) or row['volume'] <= 0:
            return False, f"volume <= 0 or NaN: {row.get('volume')}"
        
        # 2. 價格邏輯關係
        low = row.get('low')
        high = row.get('high')
        close = row.get('close')
        
        if not pd.isna(low) and not pd.isna(high):
            if low > high:
                return False, f"low ({low}) > high ({high})"
            
            if not (low <= close <= high):
                return False, f"close ({close}) not in [low ({low}), high ({high})]"
        
        # 3. 異常跳動檢查（與前日比較）
        if prev_close and prev_close > 0:
            prev_close_float = float(prev_close)  # PATCH: 確保是 float，避免 Decimal vs float
            change_pct = abs(close - prev_close_float) / prev_close_float
            
            # 一般股票 ±10%，創新板 ±15%（這裡用較寬鬆的 15%）
            if change_pct > 0.15:
                return False, f"jump > 15%: {prev_close} -> {close} ({change_pct:.1%})"
        
        return True, "OK"
    
    @staticmethod
    def validate_date_batch(date_obj, prices_df, min_records=1500):
        """
        Layer 2: 當日批次檢驗
        
        Args:
            date_obj: 日期物件
            prices_df: 當日所有股票的 DataFrame
            min_records: 最少筆數（預設 1500，台股上市+上櫃約 1700~1800）
        
        Returns:
            (is_valid: bool, reason: str)
        """
        # 1. 當日必須是交易日（排除週末）
        if date_obj.weekday() >= 5:
            return False, f"{date_obj} is weekend"
        
        # 2. 筆數檢查
        if len(prices_df) < min_records:
            return False, f"only {len(prices_df)} records (< {min_records})"
        
        # 3. 抽樣驗證：檢查是否有明顯異常值
        sample = prices_df.sample(n=min(20, len(prices_df)))
        invalid_count = 0
        for _, row in sample.iterrows():
            valid, reason = PriceValidator.validate_row(row.to_dict())
            if not valid:
                invalid_count += 1
        
        if invalid_count > 5:  # 超過 5 筆異常，視為當日資料有問題
            return False, f"{invalid_count}/20 sample records invalid"
        
        return True, f"{len(prices_df)} records, {invalid_count}/20 sample OK"
    
    @staticmethod
    def get_prev_close(stock_code, target_date):
        """
        從資料庫取得前一日收盤價（如果有）
        """
        from apps.market_data.models import DailyPrice, Stock
        
        try:
            stock = Stock.objects.filter(code=stock_code).first()
            if not stock:
                return None
            
            prev = DailyPrice.objects.filter(
                stock=stock,
                date__lt=target_date
            ).order_by('-date').first()
            
            return prev.close if prev else None
        except Exception:
            return None
