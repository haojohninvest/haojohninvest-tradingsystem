import os
import re
import pandas as pd
import numpy as np
from pathlib import Path
from decimal import Decimal
from django.core.management.base import BaseCommand
from django.db import transaction
from apps.market_data.models import Stock, DailyPrice, StockSharesHistory
from apps.analysis.models import Indicator
from apps.sectors.models import Sector, StockSector

RAW_DATA_DIR = Path(r'C:\Users\user\OneDrive\OneDrive_Desktop\3交易系統\raw_data')
EXCEL_PATH = RAW_DATA_DIR / 'For_Python.xlsx'
REFERENCE_DATE = pd.Timestamp('2025-01-02').date()

TWSE_DIR = RAW_DATA_DIR / 'twse'
OTC_DIR = RAW_DATA_DIR / 'otc'

BATCH_SIZE = 1000


def get_price_cols(all_cols):
    """Extract pure stock code columns (e.g. '1101', '1101B', '2330')."""
    return [c for c in all_cols if c != 'Date' and re.match(r'^\d{4,5}[A-Z]?$', c)]


def get_ema_cols(all_cols):
    """Extract _EMA20, _EMA60, _EMA120 columns."""
    return {
        'ema20': [c for c in all_cols if re.match(r'^\d{4,5}[A-Z]?_EMA20$', c)],
        'ema60': [c for c in all_cols if re.match(r'^\d{4,5}[A-Z]?_EMA60$', c)],
        'ema120': [c for c in all_cols if re.match(r'^\d{4,5}[A-Z]?_EMA120$', c)],
    }


class Command(BaseCommand):
    help = 'Import raw OHLCV + EMA + market cap data from CSV/Excel into SQLite DB'

    def handle(self, *args, **options):
        self.stdout.write(self.style.WARNING("=== Import Raw Data into SQLite ==="))

        # Step 1: Read Excel basic info
        self._load_excel_info()

        # Step 2: Import TWSE
        self._import_market('twse', TWSE_DIR)

        # Step 3: Import OTC
        self._import_market('otc', OTC_DIR)

        # Step 4: Import StockSharesHistory (from Excel market cap)
        self._import_shares_history()

        # Step 5: Import StockSector (from Excel sector classification)
        self._import_stock_sectors()

        self.stdout.write(self.style.SUCCESS("=== Import Complete! ==="))

    # ------------------------------------------------------------------
    # Excel helpers
    # ------------------------------------------------------------------
    def _load_excel_info(self):
        self.stdout.write("Loading Excel sheets...")
        xl = pd.ExcelFile(str(EXCEL_PATH))

        # ---- Sheet 0: Stock list ----
        self.stock_list_df = xl.parse(xl.sheet_names[0])
        self.stock_list_df.columns = self.stock_list_df.columns.astype(str)
        # First column format: "1101 台泥"
        self.stock_list_df['code'] = (
            self.stock_list_df.iloc[:, 0]
            .astype(str)
            .str.split()
            .str[0]
        )
        self.stock_list_df['name'] = (
            self.stock_list_df.iloc[:, 0]
            .astype(str)
            .str.split(n=1)
            .str[1]
            .fillna('')
        )
        self.stock_list_map = dict(
            zip(self.stock_list_df['code'], self.stock_list_df['name'])
        )

        # ---- Sheet 3: Market cap (市值) ----
        self.mcap_df = xl.parse(xl.sheet_names[3])
        self.mcap_df.columns = self.mcap_df.columns.astype(str)
        self.mcap_df['code'] = (
            self.mcap_df.iloc[:, 0]
            .astype(str)
            .str.split()
            .str[0]
        )
        self.mcap_df['mcap_million'] = pd.to_numeric(
            self.mcap_df.iloc[:, 1], errors='coerce'
        )
        self.mcap_map = dict(
            zip(self.mcap_df['code'], self.mcap_df['mcap_million'])
        )

        # ---- Sheet 9: Sector classification (族群分類) ----
        self.sector_df = xl.parse(xl.sheet_names[9])
        self.sector_df.columns = self.sector_df.columns.astype(str)
        self.sector_df['code'] = (
            self.sector_df.iloc[:, 0]
            .astype(str)
            .str.split()
            .str[0]
        )
        self.sector_df['sector_name'] = (
            self.sector_df.iloc[:, 1]
            .astype(str)
            .str.strip()
        )
        self.sector_df = self.sector_df.dropna(subset=['sector_name'])
        self.sector_df = self.sector_df[self.sector_df['sector_name'] != '']

        self.stdout.write(
            f"  Loaded {len(self.stock_list_map)} stocks, "
            f"{len(self.mcap_map)} market-cap entries, "
            f"{len(self.sector_df)} sector mappings"
        )

    # ------------------------------------------------------------------
    # Market (twse / otc) import
    # ------------------------------------------------------------------
    def _import_market(self, market, data_dir):
        self.stdout.write(f"\n--- Importing {market.upper()} ---")

        # --- Read headers ---
        close_cols = pd.read_csv(data_dir / 'close.csv', nrows=0).columns.tolist()
        open_cols = pd.read_csv(data_dir / 'open.csv', nrows=0).columns.tolist()
        high_cols = pd.read_csv(data_dir / 'high.csv', nrows=0).columns.tolist()
        low_cols = pd.read_csv(data_dir / 'low.csv', nrows=0).columns.tolist()
        volume_cols = pd.read_csv(
            data_dir / 'volume.csv', nrows=0
        ).columns.tolist()

        price_cols = get_price_cols(open_cols)   # master stock list
        ema_map = get_ema_cols(close_cols)

        self.stdout.write(
            f"  Price stocks: {len(price_cols)} | "
            f"EMA20: {len(ema_map['ema20'])} | "
            f"EMA60: {len(ema_map['ema60'])} | "
            f"EMA120: {len(ema_map['ema120'])}"
        )

        # --- Create Stock records ---
        self._create_stocks(market, price_cols)

        # --- Read close.csv (price + EMA) ---
        close_price_cols = [c for c in price_cols if c in close_cols]
        close_usecols = (
            ['Date']
            + close_price_cols
            + ema_map['ema20']
            + ema_map['ema60']
            + ema_map['ema120']
        )
        self.stdout.write(
            f"  Reading close.csv ({len(close_usecols)} cols)..."
        )
        close_df = pd.read_csv(
            data_dir / 'close.csv',
            usecols=close_usecols,
            dtype={c: np.float32 for c in close_usecols if c != 'Date'},
            low_memory=False,
        )
        close_df['Date'] = pd.to_datetime(close_df['Date']).dt.date

        # --- Read open/high/low/volume ---
        self.stdout.write("  Reading open/high/low/volume...")
        open_df = self._read_price_df(
            data_dir / 'open.csv', price_cols, open_cols
        )
        high_df = self._read_price_df(
            data_dir / 'high.csv', price_cols, high_cols
        )
        low_df = self._read_price_df(
            data_dir / 'low.csv', price_cols, low_cols
        )
        volume_df = self._read_price_df(
            data_dir / 'volume.csv', price_cols, volume_cols
        )

        # --- Import DailyPrice ---
        self._import_daily_prices(
            market,
            close_df,
            open_df,
            high_df,
            low_df,
            volume_df,
            close_price_cols,
        )

        # --- Import Indicator ---
        self._import_indicators(
            market, close_df, ema_map, close_price_cols
        )

    def _read_price_df(self, path, price_cols, available_cols):
        cols_to_read = ['Date'] + [c for c in price_cols if c in available_cols]
        df = pd.read_csv(
            path,
            usecols=cols_to_read,
            dtype={c: np.float32 for c in cols_to_read if c != 'Date'},
        )
        df['Date'] = pd.to_datetime(df['Date']).dt.date
        return df

    def _create_stocks(self, market, price_cols):
        existing_codes = set(
            Stock.objects.filter(market=market)
            .values_list('code', flat=True)
        )
        new_stocks = []
        for code in price_cols:
            if code in existing_codes:
                continue
            name = self.stock_list_map.get(code, '')
            if not name:
                name = code
            new_stocks.append(Stock(code=code, name=name, market=market))

        if new_stocks:
            Stock.objects.bulk_create(new_stocks, ignore_conflicts=True)
            self.stdout.write(
                f"  Created {len(new_stocks)} new stocks for {market}"
            )

        self.stock_id_map = {
            s.code: s.id for s in Stock.objects.filter(market=market)
        }

    def _import_daily_prices(self, market, close_df, open_df, high_df, low_df,
                             volume_df, price_cols):
        self.stdout.write(f"  Importing DailyPrice for {market}...")

        # Build fast lookups: {date: Series}
        self.stdout.write("    Building date lookups...")
        open_lookup = {
            row['Date']: row for _, row in open_df.iterrows()
        }
        high_lookup = {
            row['Date']: row for _, row in high_df.iterrows()
        }
        low_lookup = {
            row['Date']: row for _, row in low_df.iterrows()
        }
        volume_lookup = {
            row['Date']: row for _, row in volume_df.iterrows()
        }

        records = []
        imported = 0
        dates = close_df['Date'].unique()
        total_dates = len(dates)

        for i, date_val in enumerate(dates):
            if pd.isna(date_val):
                continue

            close_row = close_df[close_df['Date'] == date_val].iloc[0]
            open_row = open_lookup.get(date_val)
            high_row = high_lookup.get(date_val)
            low_row = low_lookup.get(date_val)
            volume_row = volume_lookup.get(date_val)

            for code in price_cols:
                stock_id = self.stock_id_map.get(code)
                if not stock_id:
                    continue

                close_v = self._get_val(close_row, code)
                if close_v is None:
                    continue

                open_v = self._get_val(open_row, code)
                high_v = self._get_val(high_row, code)
                low_v = self._get_val(low_row, code)
                volume_v = self._get_vol(volume_row, code)

                records.append(
                    DailyPrice(
                        stock_id=stock_id,
                        date=date_val,
                        open=open_v,
                        high=high_v,
                        low=low_v,
                        close=close_v,
                        volume=volume_v,
                    )
                )

                if len(records) >= BATCH_SIZE:
                    DailyPrice.objects.bulk_create(
                        records, ignore_conflicts=True
                    )
                    imported += len(records)
                    records = []

            if (i + 1) % 50 == 0 or (i + 1) == total_dates:
                self.stdout.write(
                    f"    ... {i + 1}/{total_dates} dates processed, "
                    f"{imported} records inserted"
                )

        if records:
            DailyPrice.objects.bulk_create(records, ignore_conflicts=True)
            imported += len(records)

        self.stdout.write(
            f"  DailyPrice imported: {imported} records for {market}"
        )

    def _import_indicators(self, market, close_df, ema_map, price_cols):
        self.stdout.write(f"  Importing Indicator for {market}...")

        # Build code -> {ema_type: col_name}
        code_to_emas = {}
        for ind_type, cols in ema_map.items():
            for col in cols:
                code = col.split('_')[0]
                if code in price_cols:
                    code_to_emas.setdefault(code, {})[ind_type] = col

        records = []
        imported = 0
        dates = close_df['Date'].unique()
        total_dates = len(dates)

        for i, date_val in enumerate(dates):
            if pd.isna(date_val):
                continue

            row = close_df[close_df['Date'] == date_val].iloc[0]

            for code, ema_cols in code_to_emas.items():
                stock_id = self.stock_id_map.get(code)
                if not stock_id:
                    continue

                vals = {}
                has_any = False
                for ind_type, col in ema_cols.items():
                    try:
                        v = row[col]
                        if not pd.isna(v) and v != 0.0:
                            vals[ind_type] = round(float(v), 2)
                            has_any = True
                    except (KeyError, TypeError):
                        pass

                if has_any:
                    records.append(
                        Indicator(
                            stock_id=stock_id,
                            date=date_val,
                            ema20=vals.get('ema20'),
                            ema60=vals.get('ema60'),
                            ema120=vals.get('ema120'),
                        )
                    )

                if len(records) >= BATCH_SIZE:
                    Indicator.objects.bulk_create(
                        records, ignore_conflicts=True
                    )
                    imported += len(records)
                    records = []

            if (i + 1) % 50 == 0 or (i + 1) == total_dates:
                self.stdout.write(
                    f"    ... {i + 1}/{total_dates} dates processed, "
                    f"{imported} indicator records inserted"
                )

        if records:
            Indicator.objects.bulk_create(records, ignore_conflicts=True)
            imported += len(records)

        self.stdout.write(
            f"  Indicator imported: {imported} records for {market}"
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _get_val(self, row, col):
        if row is None:
            return None
        try:
            v = row[col]
            if pd.isna(v) or v == 0.0:
                return None
            return round(float(v), 2)
        except (KeyError, TypeError):
            return None

    def _get_vol(self, row, col):
        if row is None:
            return None
        try:
            v = row[col]
            if pd.isna(v) or v == 0.0:
                return None
            return int(float(v))
        except (KeyError, TypeError):
            return None

    # ------------------------------------------------------------------
    # StockSharesHistory (market cap -> shares)
    # ------------------------------------------------------------------
    def _import_shares_history(self):
        self.stdout.write("\n--- Importing StockSharesHistory ---")

        ref_prices = DailyPrice.objects.filter(
            date=REFERENCE_DATE
        ).values('stock_id', 'close')
        price_map = {
            p['stock_id']: float(p['close']) for p in ref_prices
        }

        records = []
        created = 0
        skipped = 0

        for code, mcap_million in self.mcap_map.items():
            try:
                stock = Stock.objects.get(code=code)
            except Stock.DoesNotExist:
                skipped += 1
                continue

            close_price = price_map.get(stock.id)
            if close_price and close_price > 0:
                mcap_yuan = mcap_million * 1_000_000
                shares = int(mcap_yuan / close_price)
            else:
                shares = 0

            records.append(
                StockSharesHistory(
                    stock_id=stock.id,
                    date=REFERENCE_DATE,
                    outstanding_shares=shares,
                    source='excel_mcap',
                )
            )
            created += 1

        if records:
            StockSharesHistory.objects.bulk_create(
                records, ignore_conflicts=True
            )

        self.stdout.write(
            f"  Created {created} shares records, skipped {skipped} "
            f"(ref date: {REFERENCE_DATE})"
        )

    # ------------------------------------------------------------------
    # Sector / StockSector
    # ------------------------------------------------------------------
    def _import_stock_sectors(self):
        self.stdout.write("\n--- Importing Sectors & StockSectors ---")

        sector_names = self.sector_df['sector_name'].unique()
        existing = {s.name: s.id for s in Sector.objects.all()}
        new_sectors = []
        for name in sector_names:
            if name not in existing:
                new_sectors.append(Sector(name=name))

        if new_sectors:
            Sector.objects.bulk_create(new_sectors, ignore_conflicts=True)
            existing = {s.name: s.id for s in Sector.objects.all()}

        stock_id_by_code = {
            s.code: s.id for s in Stock.objects.all()
        }

        records = []
        dup = 0
        seen = set()
        for _, row in self.sector_df.iterrows():
            code = row['code']
            sector_name = row['sector_name']
            stock_id = stock_id_by_code.get(code)
            sector_id = existing.get(sector_name)

            if not stock_id or not sector_id:
                continue

            key = (stock_id, sector_id)
            if key in seen:
                dup += 1
                continue
            seen.add(key)

            records.append(StockSector(stock_id=stock_id, sector_id=sector_id))

        if records:
            StockSector.objects.bulk_create(records, ignore_conflicts=True)

        self.stdout.write(
            f"  Created {len(existing)} sectors, "
            f"{len(records)} stock-sector mappings (skipped {dup} dupes)"
        )

