"""
Scheduler Service for Haoqiang Capital Trading System
Automatically executes daily and weekly tasks:
- Daily (Mon-Fri 13:30): Crawl stock prices, calculate indicators, calculate market breadth, calculate divergence
- Weekly (Sun 01:00): Full recalculation from 2020
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
    """Daily tasks: crawl prices, calculate indicators, calculate divergence, health check"""
    logger.info('Starting daily tasks...')
    
    try:
        # 1. Crawl daily stock prices
        logger.info('[1/5] Crawling daily stock prices...')
        call_command('run_crawler')
        logger.info('[OK] Stock crawl completed')
        
        # 2. Calculate technical indicators
        logger.info('[2/5] Calculating technical indicators...')
        call_command('calc_indicators')
        logger.info('[OK] Technical indicators completed')
        
        # 3. Calculate market breadth
        logger.info('[3/5] Calculating market breadth...')
        call_command('calc_market_breadth', days=7)
        logger.info('[OK] Market breadth completed')
        
        # 4. Calculate sector divergence
        logger.info('[4/5] Calculating sector divergence...')
        call_command('calc_divergence')
        logger.info('[OK] Sector divergence completed')
        
        # 5. Health check
        logger.info('[5/5] Running stock health check...')
        call_command('check_stock_health')
        logger.info('[OK] Health check completed')
        
        logger.info('=== Daily tasks completed ===')
        
    except Exception as e:
        logger.error(f'[ERROR] Daily tasks failed: {str(e)}')
        raise

def run_weekly_recalc():
    """Weekly task: recalculate all data from 2020"""
    logger.info('Starting weekly full recalculation...')
    
    try:
        logger.info('[Weekly] Recrawling all historical data from 2020-01-01...')
        call_command('run_crawler', start_date='2020-01-01')
        logger.info('[OK] Historical data crawl completed')
        
        logger.info('[Weekly] Recalculating all indicators...')
        call_command('calc_indicators')
        logger.info('[OK] Technical indicators completed')
        
        logger.info('[Weekly] Recalculating sector divergence...')
        call_command('calc_divergence')
        logger.info('[OK] Sector divergence completed')
        
        logger.info('=== Weekly full recalculation completed ===')
        
    except Exception as e:
        logger.error(f'[ERROR] Weekly recalculation failed: {str(e)}')
        raise

class Command(BaseCommand):
    help = 'Start scheduler service (auto-execute daily tasks)'

    def handle(self, *args, **options):
        logger.info('Starting scheduler service...')
        
        # Create scheduler
        scheduler = BlockingScheduler(timezone='Asia/Taipei')
        scheduler.add_jobstore(DjangoJobStore(), 'default')
        
        # Daily task (Mon-Fri 14:30) - 台股 13:30 收盤，證交所約 14:00-14:30 更新 API
        scheduler.add_job(
            run_daily_tasks,
            trigger=CronTrigger(day_of_week='mon-fri', hour='14', minute='30'),
            id='daily_crawl_and_calc',
            name='Daily Stock Crawl & Calculation',
            replace_existing=True
        )
        logger.info('[OK] Added daily task (Mon-Fri 14:30)')
        
        # Weekly task (Sun 01:00)
        scheduler.add_job(
            run_weekly_recalc,
            trigger=CronTrigger(day_of_week='sun', hour='1', minute='0'),
            id='weekly_recalc',
            name='Weekly Full Recalculation',
            replace_existing=True
        )
        logger.info('[OK] Added weekly task (Sun 01:00)')
        
        logger.info('')
        logger.info('=== Scheduler started ===')
        logger.info('Press Ctrl+C to stop')
        logger.info('')
        
        try:
            scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            logger.info('Scheduler stopped.')
