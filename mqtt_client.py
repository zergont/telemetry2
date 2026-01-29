"""
Universal Modbus Decoder - MQTT Client

Handles MQTT connection, subscription to raw telemetry,
and publication of decoded data.
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
            logger.info(f"Connected to MQTT broker at {self.host}:{self.port}")
            self._connected = True
            
            # Subscribe to raw telemetry
            client.subscribe(self.raw_topic_pattern)
            logger.info(f"Subscribed to: {self.raw_topic_pattern}")
        else:
            logger.error(f"Failed to connect to MQTT broker, rc={rc}")
            self._connected = False
    
    def _on_disconnect(self, client, userdata, rc, properties=None):
        """Callback when disconnected from broker."""
        logger.warning(f"Disconnected from MQTT broker, rc={rc}")
        self._connected = False
    
    def _on_message(self, client, userdata, msg):
        """Callback when message received."""
        self.messages_received += 1
        
        try:
            self._process_message(msg.topic, msg.payload)
        except Exception as e:
            logger.error(f"Error processing message: {e}")
            self.decode_errors += 1
    
    def _process_message(self, topic: str, payload: bytes):
        """Process a raw telemetry message."""
        # Extract router SN from topic
        match = self._topic_regex.search(topic)
        if not match:
            if self.debug_mode:
                logger.debug(f"Topic doesn't match pattern: {topic}")
            return
        
        router_sn = match.group(1)
        
        # Parse JSON payload
        try:
            data = json.loads(payload.decode('utf-8'))
        except json.JSONDecodeError as e:
            logger.warning(f"Invalid JSON payload: {e}")
            self.decode_errors += 1
            return
        
        # Extract Modbus_PCC data
        modbus_pcc = data.get('Modbus_PCC')
        if not modbus_pcc:
            if self.debug_mode:
                logger.debug(f"No Modbus_PCC in payload")
            return
        
        # Extract fields
        date_iso = modbus_pcc.get('date_iso_8601')
        bserver_id = modbus_pcc.get('bserver_id')
        full_addr = modbus_pcc.get('full_addr')
        data_str = modbus_pcc.get('data')
        
        if bserver_id is None or full_addr is None or data_str is None:
            logger.warning(f"Missing required fields in Modbus_PCC")
            self.decode_errors += 1
            return
        
        # Parse data array
        try:
            words = json.loads(data_str)
            if not isinstance(words, list):
                words = [words]
        except json.JSONDecodeError:
            logger.warning(f"Invalid data array: {data_str}")
            self.decode_errors += 1
            return
        
        if self.debug_mode:
            logger.debug(f"RAW: router={router_sn}, bserver={bserver_id}, addr={full_addr}, data={words}")
        
        # Decode
        decoder = get_decoder(debug_mode=self.debug_mode)
        decoded_registers = decoder.decode_packet(full_addr, words)
        
        if not decoded_registers:
            if self.debug_mode:
                logger.debug(f"No registers decoded for {full_addr}")
            return
        
        self.messages_decoded += 1
        
        # Update store
        store = get_store()
        
        # Extract GPS if available (from top-level data)
        gps_lat = data.get('gps_lat')
        gps_lon = data.get('gps_lon')
        gps_time = data.get('gps_time')
        
        store.update_panel(
            router_sn=router_sn,
            bserver_id=bserver_id,
            decoded_registers=decoded_registers,
            gps_lat=gps_lat,
            gps_lon=gps_lon,
            gps_time=date_iso or gps_time
        )
        
        # Publish decoded data
        self._publish_decoded(router_sn, bserver_id, decoded_registers, date_iso)
    
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
                logger.debug(f"Published decoded to {topic}: {len(decoded_registers)} registers")
        except Exception as e:
            logger.error(f"Failed to publish decoded: {e}")
    
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
            logger.info(f"Connecting to MQTT broker at {self.host}:{self.port}...")
            self._client.connect(self.host, self.port, keepalive=60)
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to connect to MQTT broker: {e}")
            return False
    
    def start(self):
        """Start the MQTT client loop (non-blocking)."""
        if self._client:
            self._client.loop_start()
            logger.info("MQTT client loop started")
    
    def stop(self):
        """Stop the MQTT client."""
        if self._client:
            self._client.loop_stop()
            self._client.disconnect()
            logger.info("MQTT client stopped")
    
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
