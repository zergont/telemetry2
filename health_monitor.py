"""
Универсальный Modbus-декодер — Монитор состояния

Периодически проверяет состояние панелей и обновляет статусы.
"""

import logging
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler

from panel_store import get_store

logger = logging.getLogger(__name__)


class HealthMonitor:
    """
    Monitors health status of panels.
    Updates status based on last_seen timestamps.
    """
    
    def __init__(self, check_interval_sec: float = 5.0):
        self.check_interval = check_interval_sec
        self._scheduler: Optional[BackgroundScheduler] = None
        self._running = False
    
    def _check_health(self):
        """Periodic health check job."""
        try:
            store = get_store()
            store.update_health_status()
        except Exception as e:
            logger.error(f"Ошибка проверки состояния: {e}")
    
    def start(self):
        """Start the health monitor."""
        if self._running:
            return
        
        self._scheduler = BackgroundScheduler()
        self._scheduler.add_job(
            self._check_health,
            'interval',
            seconds=self.check_interval,
            id='health_check'
        )
        self._scheduler.start()
        self._running = True
        logger.info(f"Монитор состояния запущен (интервал: {self.check_interval}с)")
    
    def stop(self):
        """Stop the health monitor."""
        if self._scheduler:
            self._scheduler.shutdown(wait=False)
            self._scheduler = None
        self._running = False
        logger.info("Монитор состояния остановлен")
    
    def is_running(self) -> bool:
        """Check if monitor is running."""
        return self._running


# Global monitor instance
_health_monitor: Optional[HealthMonitor] = None


def get_health_monitor() -> Optional[HealthMonitor]:
    """Get the global health monitor instance."""
    return _health_monitor


def init_health_monitor(check_interval_sec: float = 5.0) -> HealthMonitor:
    """Initialize the global health monitor."""
    global _health_monitor
    _health_monitor = HealthMonitor(check_interval_sec=check_interval_sec)
    return _health_monitor
