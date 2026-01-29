"""
Universal Modbus Decoder - Panel State Store

In-memory storage for panel states and decoded data.
Panels are discovered dynamically from incoming messages.
"""

import time
import threading
import logging
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
    
    # Last message timestamp
    last_seen: float = 0.0
    
    # GPS data (if available)
    gps_lat: Optional[float] = None
    gps_lon: Optional[float] = None
    gps_time: Optional[str] = None
    
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
    
    # GPS data from last message
    gps_lat: Optional[float] = None
    gps_lon: Optional[float] = None
    gps_time: Optional[str] = None
    
    # Panel IDs connected to this router
    panel_ids: set = field(default_factory=set)
    
    # Last seen timestamp
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
        self.offline_threshold = offline_threshold_sec
    
    def _panel_key(self, router_sn: str, bserver_id: int) -> str:
        """Generate panel key from router SN and bserver ID."""
        return f"{router_sn}:{bserver_id}"
    
    def get_or_create_panel(self, router_sn: str, bserver_id: int) -> PanelState:
        """Get existing panel or create new one (dynamic discovery)."""
        key = self._panel_key(router_sn, bserver_id)
        
        with self._lock:
            if key not in self._panels:
                logger.info(f"Discovered new panel: router={router_sn}, bserver_id={bserver_id}")
                self._panels[key] = PanelState(
                    router_sn=router_sn,
                    bserver_id=bserver_id
                )
                
                # Also update router
                self._ensure_router(router_sn)
                self._routers[router_sn].panel_ids.add(bserver_id)
            
            return self._panels[key]
    
    def _ensure_router(self, router_sn: str) -> RouterState:
        """Ensure router exists."""
        if router_sn not in self._routers:
            logger.info(f"Discovered new router: {router_sn}")
            self._routers[router_sn] = RouterState(sn=router_sn)
        return self._routers[router_sn]
    
    def update_panel(self, router_sn: str, bserver_id: int, 
                     decoded_registers: List[dict],
                     gps_lat: Optional[float] = None,
                     gps_lon: Optional[float] = None,
                     gps_time: Optional[str] = None) -> None:
        """
        Update panel state with new decoded data.
        """
        panel = self.get_or_create_panel(router_sn, bserver_id)
        
        with self._lock:
            now = time.time()
            panel.last_seen = now
            panel.message_count += 1
            panel.status = PanelStatus.ONLINE
            
            # Update GPS if provided
            if gps_lat is not None:
                panel.gps_lat = gps_lat
            if gps_lon is not None:
                panel.gps_lon = gps_lon
            if gps_time is not None:
                panel.gps_time = gps_time
            
            # Update registers
            for reg in decoded_registers:
                addr = reg.get('addr')
                if addr is not None:
                    panel.registers[addr] = reg
            
            # Update router
            router = self._ensure_router(router_sn)
            router.last_seen = now
            if gps_lat is not None:
                router.gps_lat = gps_lat
            if gps_lon is not None:
                router.gps_lon = gps_lon
            if gps_time is not None:
                router.gps_time = gps_time
    
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
                        logger.info(f"Panel {panel.router_sn}:{panel.bserver_id} -> OFFLINE")
                    panel.status = PanelStatus.OFFLINE
                elif age > self.stale_threshold:
                    if panel.status != PanelStatus.STALE:
                        logger.info(f"Panel {panel.router_sn}:{panel.bserver_id} -> STALE")
                    panel.status = PanelStatus.STALE
                else:
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
