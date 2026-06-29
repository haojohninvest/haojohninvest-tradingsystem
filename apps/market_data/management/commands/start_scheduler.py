"""
Scheduler Service for Haoqiang Capital Trading System
Automatically executes daily tasks (every day at 14:30 and 15:00)
"""
from django.core.management.base import BaseCommand
from django_apscheduler.jobstores import DjangoJobStore
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from django.core.management import call_command
import logging
import sys

logger = logging.getLogger('apps')

def run_daily_tasks():
    """Daily tasks: crawl prices, calculate indicators, calculate divergence, run scanner"""
    from datetime import date, timedelta
    logger.info('Starting daily tasks...')
    
    try:
        # 1. Crawl daily stock prices
        logger.info('[1/5] Crawling daily stock prices...')
        call_command('backfill_runner', resume=True)
        logger.info('[OK] Stock crawl completed')
        
        # 2. Calculate technical indicators
        logger.info('[2/5] Calculating technical indicators...')
        call_command('calc_indicators', days=14)
        logger.info('[OK] Technical indicators completed')
        
        # 3. Calculate market breadth
        logger.info('[3/5] Calculating market breadth...')
        call_command('calc_market_breadth', days=7)
        logger.info('[OK] Market breadth completed')
        
        # 4. Calculate sector divergence
        logger.info('[4/5] Calculating sector divergence...')
        call_command('calc_divergence')
        logger.info('[OK] Sector divergence completed')
        
        # 5. Stock pick scanner (最近 120 個交易日)
        logger.info('[5/5] Running stock pick scanner...')
        today = date.today()
        scan_end = today.strftime('%Y-%m-%d')
        scan_start = (today - timedelta(days=120)).strftime('%Y-%m-%d')
        call_command('stock_pick_scanner', start_date=scan_start, end_date=scan_end, output_db=True)
        logger.info(f'[OK] Stock pick scanner completed ({scan_start} ~ {scan_end})')
        
        logger.info('=== Daily tasks completed ===')
        
    except Exception as e:
        logger.error(f'[ERROR] Daily tasks failed: {str(e)}')
        raise

class Command(BaseCommand):
    help = 'Start scheduler service (auto-execute daily tasks)'

    def handle(self, *args, **options):
        logger.info('Starting scheduler service...')
        
        # Create scheduler
        scheduler = BlockingScheduler(timezone='Asia/Taipei')
        scheduler.add_jobstore(DjangoJobStore(), 'default')
        
        # Daily task (every day 14:30)
        scheduler.add_job(
            run_daily_tasks,
            trigger=CronTrigger(hour='14', minute='30'),
            id='daily_crawl_and_calc',
            name='Daily Stock Crawl & Calculation',
            replace_existing=True
        )
        logger.info('[OK] Added daily task (14:30)')
        
        # Daily task (every day 15:00)
        scheduler.add_job(
            run_daily_tasks,
            trigger=CronTrigger(hour='15', minute='00'),
            id='daily_crawl_and_calc_1500',
            name='Daily Stock Crawl & Calculation (15:00)',
            replace_existing=True
        )
        logger.info('[OK] Added daily task (15:00)')
        
        logger.info('')
        logger.info('=== Scheduler started ===')
        logger.info('Press Ctrl+C to stop')
        logger.info('')
        
        try:
            scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            logger.info('Scheduler stopped.')
