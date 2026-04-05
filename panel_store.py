"""
Универсальный Modbus-декодер — Хранилище панелей

In-memory хранилище состояний панелей и декодированных данных.
Панели обнаруживаются динамически при получении данных.
"""

import time
import threading
import logging
from collections import deque
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class PanelStatus(Enum):
    """Panel health status."""
    ONLINE = "online"
    STALE = "stale"
    OFFLINE = "offline"


@dataclass
class PanelState:
    """State of a single Modbus panel."""
    router_sn: str
    bserver_id: int

    # Device type (e.g. 'pcc', 'dse')
    device_type: str = 'pcc'

    # Last message timestamp
    last_seen: float = 0.0

    # Last decoded registers: addr -> decoded dict
    registers: Dict[int, dict] = field(default_factory=dict)

    # Current status
    status: PanelStatus = PanelStatus.OFFLINE

    # Message counters
    message_count: int = 0
    decode_error_count: int = 0


@dataclass
class RouterState:
    """State of a router (may have multiple panels)."""
    sn: str
    
    # GPS data (from GPS messages, not from panels)
    gps_lat: Optional[float] = None
    gps_lon: Optional[float] = None
    gps_alt: Optional[float] = None
    gps_speed: Optional[float] = None
    gps_angle: Optional[float] = None
    gps_accuracy: Optional[float] = None
    gps_satellites: Optional[int] = None
    gps_fix_status: Optional[int] = None
    gps_time: Optional[str] = None
    
    # Panel IDs connected to this router
    panel_ids: set = field(default_factory=set)
    
    # Last seen timestamp (any message: GPS or PCC)
    last_seen: float = 0.0


class PanelStore:
    """
    In-memory store for panel and router states.
    Thread-safe for concurrent access.
    """
    
    def __init__(self, stale_threshold_sec: float = 10.0, offline_threshold_sec: float = 60.0):
        self._lock = threading.RLock()
        
        # Panels: key = "router_sn:bserver_id"
        self._panels: Dict[str, PanelState] = {}
        
        # Routers: key = router_sn
        self._routers: Dict[str, RouterState] = {}
        
        # Health thresholds
        self.stale_threshold = stale_threshold_sec

        # Decode error log (last N errors with context)
        self._decode_errors: deque = deque(maxlen=100)
        self.offline_threshold = offline_threshold_sec
    
    def _panel_key(self, router_sn: str, bserver_id: int) -> str:
        """Generate panel key from router SN and bserver ID."""
        return f"{router_sn}:{bserver_id}"
    
    def get_or_create_panel(self, router_sn: str, bserver_id: int, device_type: str = 'pcc') -> PanelState:
        """Get existing panel or create new one (dynamic discovery)."""
        key = self._panel_key(router_sn, bserver_id)

        with self._lock:
            if key not in self._panels:
                logger.info(f"Обнаружена новая панель: роутер={router_sn}, панель={bserver_id}, тип={device_type}")
                self._panels[key] = PanelState(
                    router_sn=router_sn,
                    bserver_id=bserver_id,
                    device_type=device_type
                )
                
                # Also update router
                self._ensure_router(router_sn)
                self._routers[router_sn].panel_ids.add(bserver_id)
            
            return self._panels[key]
    
    def _ensure_router(self, router_sn: str) -> RouterState:
        """Ensure router exists."""
        if router_sn not in self._routers:
            logger.info(f"Обнаружен новый роутер: {router_sn}")
            self._routers[router_sn] = RouterState(sn=router_sn)
        return self._routers[router_sn]
    
    def update_panel(self, router_sn: str, bserver_id: int,
                     decoded_registers: List[dict], device_type: str = 'pcc') -> None:
        """
        Update panel state with new decoded data.
        GPS is updated separately via update_router_gps.
        """
        panel = self.get_or_create_panel(router_sn, bserver_id, device_type=device_type)
        
        with self._lock:
            now = time.time()
            panel.last_seen = now
            panel.message_count += 1
            if panel.status != PanelStatus.ONLINE:
                logger.info(f"Панель {router_sn}:{bserver_id} -> ONLINE")
            panel.status = PanelStatus.ONLINE
            
            # Update registers
            for reg in decoded_registers:
                addr = reg.get('addr')
                if addr is not None:
                    panel.registers[addr] = reg
            
            # Touch router last_seen
            router = self._ensure_router(router_sn)
            router.last_seen = now
    
    def update_router_gps(self, router_sn: str, gps_data: dict) -> None:
        """
        Update router GPS data from a GPS message.
        
        gps_data fields: latitude, longitude, altitude, speed, angle,
                         accuracy, satellites, fix_status, date_iso_8601
        """
        with self._lock:
            router = self._ensure_router(router_sn)
            now = time.time()
            router.last_seen = now
            
            if 'latitude' in gps_data:
                router.gps_lat = gps_data['latitude']
            if 'longitude' in gps_data:
                router.gps_lon = gps_data['longitude']
            if 'altitude' in gps_data:
                router.gps_alt = gps_data['altitude']
            if 'speed' in gps_data:
                router.gps_speed = gps_data['speed']
            if 'angle' in gps_data:
                router.gps_angle = gps_data['angle']
            if 'accuracy' in gps_data:
                router.gps_accuracy = gps_data['accuracy']
            if 'satellites' in gps_data:
                router.gps_satellites = gps_data['satellites']
            if 'fix_status' in gps_data:
                router.gps_fix_status = gps_data['fix_status']
            if 'date_iso_8601' in gps_data:
                router.gps_time = gps_data['date_iso_8601']
            
            logger.debug(f"GPS обновлён для роутера {router_sn}: "
                         f"{router.gps_lat}, {router.gps_lon}")
    
    def record_decode_error(self, router_sn: str, bserver_id: int) -> None:
        """Record a decode error for a panel."""
        panel = self.get_or_create_panel(router_sn, bserver_id)
        with self._lock:
            panel.decode_error_count += 1
    
    def update_health_status(self) -> None:
        """Update health status of all panels based on last_seen time."""
        now = time.time()
        
        with self._lock:
            for panel in self._panels.values():
                age = now - panel.last_seen
                
                if age > self.offline_threshold:
                    if panel.status != PanelStatus.OFFLINE:
                        logger.info(f"Панель {panel.router_sn}:{panel.bserver_id} -> OFFLINE")
                    panel.status = PanelStatus.OFFLINE
                elif age > self.stale_threshold:
                    if panel.status != PanelStatus.STALE:
                        logger.info(f"Панель {panel.router_sn}:{panel.bserver_id} -> STALE")
                    panel.status = PanelStatus.STALE
                else:
                    if panel.status != PanelStatus.ONLINE:
                        logger.info(f"Панель {panel.router_sn}:{panel.bserver_id} -> ONLINE")
                    panel.status = PanelStatus.ONLINE
    
    def get_panel(self, router_sn: str, bserver_id: int) -> Optional[PanelState]:
        """Get panel state."""
        key = self._panel_key(router_sn, bserver_id)
        with self._lock:
            return self._panels.get(key)
    
    def get_router(self, router_sn: str) -> Optional[RouterState]:
        """Get router state."""
        with self._lock:
            return self._routers.get(router_sn)
    
    def get_all_routers(self) -> List[RouterState]:
        """Get all routers."""
        with self._lock:
            return list(self._routers.values())
    
    def get_router_panels(self, router_sn: str) -> List[PanelState]:
        """Get all panels for a router."""
        with self._lock:
            router = self._routers.get(router_sn)
            if not router:
                return []
            
            panels = []
            for bserver_id in router.panel_ids:
                key = self._panel_key(router_sn, bserver_id)
                panel = self._panels.get(key)
                if panel:
                    panels.append(panel)
            
            return sorted(panels, key=lambda p: p.bserver_id)
    
    def get_panel_registers(self, router_sn: str, bserver_id: int) -> List[dict]:
        """Get all decoded registers for a panel, sorted by address."""
        panel = self.get_panel(router_sn, bserver_id)
        if not panel:
            return []
        
        with self._lock:
            registers = list(panel.registers.values())
            return sorted(registers, key=lambda r: r.get('addr', 0))
    
    def get_stats(self) -> dict:
        """Get store statistics."""
        with self._lock:
            online = sum(1 for p in self._panels.values() if p.status == PanelStatus.ONLINE)
            stale = sum(1 for p in self._panels.values() if p.status == PanelStatus.STALE)
            offline = sum(1 for p in self._panels.values() if p.status == PanelStatus.OFFLINE)
            
            return {
                'routers': len(self._routers),
                'panels': len(self._panels),
                'online': online,
                'stale': stale,
                'offline': offline
            }

    def record_decode_error_detail(self, router_sn: str, bserver_id: int,
                                    device_type: str, addr: str,
                                    reason: str, raw_data: Any = None) -> None:
        """Record a decode error with full context."""
        with self._lock:
            self._decode_errors.append({
                'timestamp': time.time(),
                'router_sn': router_sn,
                'bserver_id': bserver_id,
                'device_type': device_type,
                'addr': addr,
                'reason': reason,
                'raw_data': str(raw_data)[:200] if raw_data is not None else None
            })

    def get_decode_errors(self, limit: int = 50) -> List[dict]:
        """Get recent decode errors."""
        with self._lock:
            errors = list(self._decode_errors)
            errors.reverse()  # newest first
            return errors[:limit]

    def clear_decode_errors(self) -> int:
        """Clear decode error log. Returns count of cleared errors."""
        with self._lock:
            count = len(self._decode_errors)
            self._decode_errors.clear()
            return count

    def clear(self) -> dict:
        """Clear all in-memory panel and router data."""
        with self._lock:
            cleared = {
                'routers': len(self._routers),
                'panels': len(self._panels)
            }
            self._routers.clear()
            self._panels.clear()
            return cleared


# Global store instance
_store: Optional[PanelStore] = None


def get_store() -> PanelStore:
    """Get the global PanelStore instance."""
    global _store
    if _store is None:
        _store = PanelStore()
    return _store


def init_store(stale_threshold_sec: float = 10.0, offline_threshold_sec: float = 60.0) -> PanelStore:
    """Initialize the global store with custom thresholds."""
    global _store
    _store = PanelStore(
        stale_threshold_sec=stale_threshold_sec,
        offline_threshold_sec=offline_threshold_sec
    )
    return _store
