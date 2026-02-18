"""
Универсальный Modbus-декодер — MQTT-клиент

Обрабатывает MQTT-соединение, подписку на raw-телеметрию
и публикацию декодированных данных.
"""

import json
import re
import logging
import threading
from typing import Callable, Optional, Any

import paho.mqtt.client as mqtt

from decoder import get_decoder
from panel_store import get_store

logger = logging.getLogger(__name__)


class MqttClient:
    """
    MQTT client for receiving raw Modbus data and publishing decoded data.
    """
    
    def __init__(self, 
                 host: str,
                 port: int = 1883,
                 client_id: str = "modbus-decoder",
                 username: str = "",
                 password: str = "",
                 reconnect_delay: int = 5,
                 raw_topic_pattern: str = "cg/v1/telemetry/SN/+",
                 decoded_topic_base: str = "cg/v1/decoded/SN",
                 debug_mode: bool = False):
        
        self.host = host
        self.port = port
        self.client_id = client_id
        self.username = username
        self.password = password
        self.reconnect_delay = reconnect_delay
        self.raw_topic_pattern = raw_topic_pattern
        self.decoded_topic_base = decoded_topic_base
        self.debug_mode = debug_mode
        
        # MQTT client
        self._client: Optional[mqtt.Client] = None
        self._connected = False
        self._lock = threading.Lock()
        
        # Regex to extract router SN from topic
        # cg/v1/telemetry/SN/<router_sn>
        self._topic_regex = re.compile(r'cg/v1/telemetry/SN/([^/]+)')
        
        # Stats
        self.messages_received = 0
        self.messages_decoded = 0
        self.messages_published = 0
        self.decode_errors = 0
    
    def _on_connect(self, client, userdata, flags, rc, properties=None):
        """Callback when connected to broker."""
        if rc == 0:
            logger.info(f"MQTT подключен к {self.host}:{self.port}")
            self._connected = True
            
            # Subscribe to raw telemetry
            client.subscribe(self.raw_topic_pattern)
            logger.info(f"Подписка на: {self.raw_topic_pattern}")
        else:
            logger.error(f"Ошибка подключения к MQTT, rc={rc}")
            self._connected = False
    
    def _on_disconnect(self, client, userdata, rc, properties=None):
        """Callback when disconnected from broker."""
        logger.warning(f"MQTT отключен, rc={rc}")
        self._connected = False
    
    def _on_message(self, client, userdata, msg):
        """Callback when message received."""
        self.messages_received += 1
        
        try:
            self._process_message(msg.topic, msg.payload)
        except Exception as e:
            logger.error(f"Ошибка обработки сообщения: {e}")
            self.decode_errors += 1
    
    @staticmethod
    def _normalize_one(inner: dict) -> Optional[dict]:
        """
        Normalize a single Modbus record into unified shape.
        Returns { date_iso, server_id, full_addr (str), data_str } or None.
        """
        # Shape A: has full_addr (string "406109") — legacy Modbus_PCC
        if 'full_addr' in inner:
            return {
                'date_iso':  inner.get('date_iso_8601'),
                'server_id': inner.get('bserver_id') or inner.get('server_id'),
                'full_addr': inner.get('full_addr'),
                'data_str':  inner.get('data'),
            }
        
        # Shape B: has addr (int offset) + data — PCC_3_3 / input2 etc.
        if 'addr' in inner and 'data' in inner:
            raw_addr = inner['addr']
            full_addr = f"4{int(raw_addr):05d}"
            return {
                'date_iso':  inner.get('date_iso_8601'),
                'server_id': inner.get('server_id') or inner.get('bserver_id'),
                'full_addr': full_addr,
                'data_str':  inner.get('data'),
            }
        
        return None
    
    @staticmethod
    def _normalize_raw(data: dict) -> list:
        """
        Raw Normalizer.
        
        Accepts any known payload shape and returns a LIST of unified dicts.
        Handles both single-object and batched-array payloads:
        
          {"PCC_3_3": {"addr": ..., "data": ...}}            → [one record]
          {"PCC_3_3": [{...}, {...}, {...}]}                  → [N records]
          {"Modbus_PCC": {"full_addr": ..., "data": ...}}     → [one record]
        
        Returns empty list if nothing recognized.
        """
        results = []
        
        for key, value in data.items():
            # Skip non-Modbus keys (e.g. GPS)
            if not isinstance(value, (dict, list)):
                continue
            
            # Single object
            if isinstance(value, dict):
                normalized = MqttClient._normalize_one(value)
                if normalized:
                    results.append(normalized)
            
            # Batched array of objects
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        normalized = MqttClient._normalize_one(item)
                        if normalized:
                            results.append(normalized)
        
        return results
    
    def _process_message(self, topic: str, payload: bytes):
        """Process a raw telemetry message."""
        # Extract router SN from topic
        match = self._topic_regex.search(topic)
        if not match:
            if self.debug_mode:
                logger.debug(f"Топик не соответствует шаблону: {topic}")
            return
        
        router_sn = match.group(1)
        
        # Parse JSON payload
        try:
            data = json.loads(payload.decode('utf-8'))
        except json.JSONDecodeError as e:
            logger.warning(f"Невалидный JSON: {e}")
            self.decode_errors += 1
            return
        
        # --- GPS message ---
        gps_data = data.get('GPS')
        if gps_data and isinstance(gps_data, dict):
            self._process_gps(router_sn, gps_data)
            return
        
        # --- Modbus PCC message (single or batched) ---
        normalized_list = self._normalize_raw(data)
        if not normalized_list:
            if self.debug_mode:
                logger.debug(f"Нераспознанная структура payload: {list(data.keys())}")
            return
        
        if self.debug_mode and len(normalized_list) > 1:
            logger.debug(f"Батч: {len(normalized_list)} пакетов в одном сообщении")
        
        for normalized in normalized_list:
            self._process_pcc(router_sn, normalized)
    
    def _process_gps(self, router_sn: str, gps_data: dict):
        """Process a GPS message and update router state."""
        store = get_store()
        store.update_router_gps(router_sn, gps_data)
        
        if self.debug_mode:
            logger.debug(f"GPS: router={router_sn}, "
                         f"lat={gps_data.get('latitude')}, "
                         f"lon={gps_data.get('longitude')}, "
                         f"sat={gps_data.get('satellites')}")
    
    def _process_pcc(self, router_sn: str, normalized: dict):
        """Process a normalized Modbus PCC message."""
        date_iso  = normalized['date_iso']
        server_id = normalized['server_id']
        full_addr = normalized['full_addr']
        data_str  = normalized['data_str']
        
        if server_id is None or full_addr is None or data_str is None:
            logger.warning(f"Отсутствуют обязательные поля после нормализации")
            self.decode_errors += 1
            return
        
        # Parse data array (may be a JSON string or already a list)
        if isinstance(data_str, str):
            try:
                words = json.loads(data_str)
                if not isinstance(words, list):
                    words = [words]
            except json.JSONDecodeError:
                logger.warning(f"Невалидный массив data: {data_str}")
                self.decode_errors += 1
                return
        elif isinstance(data_str, list):
            words = data_str
        else:
            words = [data_str]
        
        if self.debug_mode:
            logger.debug(f"RAW: router={router_sn}, server={server_id}, addr={full_addr}, data={words}")
        
        # Decode
        decoder = get_decoder(debug_mode=self.debug_mode)
        decoded_registers = decoder.decode_packet(str(full_addr), words)
        
        if not decoded_registers:
            if self.debug_mode:
                logger.debug(f"Нет декодированных регистров для {full_addr}")
            return
        
        self.messages_decoded += 1
        
        # Update store (GPS is handled separately)
        store = get_store()
        store.update_panel(
            router_sn=router_sn,
            bserver_id=server_id,
            decoded_registers=decoded_registers
        )
        
        # Publish decoded data
        self._publish_decoded(router_sn, server_id, decoded_registers, date_iso)
    
    def _publish_decoded(self, router_sn: str, bserver_id: int, 
                         decoded_registers: list, timestamp: Optional[str]):
        """Publish decoded data to MQTT."""
        if not self._connected or not self._client:
            return
        
        # Build decoded topic: cg/v1/decoded/SN/<router_sn>/pcc/<bserver_id>
        topic = f"{self.decoded_topic_base}/{router_sn}/pcc/{bserver_id}"
        
        # Build payload
        payload = {
            'timestamp': timestamp,
            'router_sn': router_sn,
            'bserver_id': bserver_id,
            'registers': decoded_registers
        }
        
        try:
            self._client.publish(topic, json.dumps(payload))
            self.messages_published += 1
            
            if self.debug_mode:
                logger.debug(f"Опубликовано в {topic}: {len(decoded_registers)} регистров")
        except Exception as e:
            logger.error(f"Ошибка публикации: {e}")
    
    def connect(self) -> bool:
        """Connect to MQTT broker."""
        try:
            # Create client with MQTTv5
            self._client = mqtt.Client(
                client_id=self.client_id,
                protocol=mqtt.MQTTv5
            )
            
            # Set callbacks
            self._client.on_connect = self._on_connect
            self._client.on_disconnect = self._on_disconnect
            self._client.on_message = self._on_message
            
            # Set credentials if provided
            if self.username:
                self._client.username_pw_set(self.username, self.password)
            
            # Enable auto-reconnect
            self._client.reconnect_delay_set(min_delay=1, max_delay=self.reconnect_delay)
            
            # Connect
            logger.info(f"Подключение к MQTT {self.host}:{self.port}...")
            self._client.connect(self.host, self.port, keepalive=60)
            
            return True
            
        except Exception as e:
            logger.error(f"Не удалось подключиться к MQTT: {e}")
            return False
    
    def start(self):
        """Start the MQTT client loop (non-blocking)."""
        if self._client:
            self._client.loop_start()
            logger.info("MQTT-клиент запущен")
    
    def stop(self):
        """Stop the MQTT client."""
        if self._client:
            self._client.loop_stop()
            self._client.disconnect()
            logger.info("MQTT-клиент остановлен")
    
    def is_connected(self) -> bool:
        """Check if connected to broker."""
        return self._connected
    
    def get_stats(self) -> dict:
        """Get client statistics."""
        return {
            'connected': self._connected,
            'messages_received': self.messages_received,
            'messages_decoded': self.messages_decoded,
            'messages_published': self.messages_published,
            'decode_errors': self.decode_errors
        }


# Global client instance
_mqtt_client: Optional[MqttClient] = None


def get_mqtt_client() -> Optional[MqttClient]:
    """Get the global MQTT client instance."""
    return _mqtt_client


def init_mqtt_client(**kwargs) -> MqttClient:
    """Initialize the global MQTT client."""
    global _mqtt_client
    _mqtt_client = MqttClient(**kwargs)
    return _mqtt_client
