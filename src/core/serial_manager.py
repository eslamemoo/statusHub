"""
serial_manager.py
=================
Manages the USB serial connection between the host PC and the ESP32-S3 smart
display (NV3041A controller).

Responsibilities
----------------
- Enumerate available COM/tty ports.
- Open and close the serial port with configurable baud rate.
- Serialise Python dicts to JSON and transmit them as UTF-8 byte frames.
- Provide a raw byte-send method for binary protocol frames.
- Emit Qt signals so the UI can react to connection state changes.

Serial frame protocol (preliminary)
------------------------------------
Each JSON message is terminated with a newline (b'\\n') so that the ESP32
firmware can use Serial.readStringUntil('\\n') to delimit packets.
Binary frames are left as-is; the caller is responsible for framing.
"""

import json
import logging
from typing import Optional

import serial
import serial.tools.list_ports
from PyQt6.QtCore import QObject, pyqtSignal

logger = logging.getLogger(__name__)


class SerialManager(QObject):
    """
    Qt-aware wrapper around a pyserial ``Serial`` instance.

    Signals
    -------
    connected(str)
        Emitted when the port is successfully opened.  Carries the port name.
    disconnected()
        Emitted when the port is closed (either by request or on error).
    send_error(str)
        Emitted when a transmission fails.
    """

    connected: pyqtSignal = pyqtSignal(str)
    disconnected: pyqtSignal = pyqtSignal()
    send_error: pyqtSignal = pyqtSignal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._serial: Optional[serial.Serial] = None

    # ------------------------------------------------------------------
    # Port enumeration
    # ------------------------------------------------------------------

    @staticmethod
    def list_ports() -> list[str]:
        """
        Return a list of available serial port device names.

        Example return value: ['/dev/ttyUSB0', '/dev/ttyACM0', 'COM3']
        """
        ports = serial.tools.list_ports.comports()
        return [port.device for port in sorted(ports)]

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def connect(self, port: str, baud_rate: int = 115200) -> bool:
        """
        Open the specified serial port.

        Parameters
        ----------
        port:
            Device path or COM port name (e.g. '/dev/ttyUSB0' or 'COM3').
        baud_rate:
            Communication speed in bits per second.  The ESP32 firmware must
            be configured with the same value.

        Returns
        -------
        bool
            ``True`` on success, ``False`` if the port could not be opened.
        """
        if self.is_connected():
            logger.warning("connect() called while already connected – ignoring.")
            return True

        try:
            self._serial = serial.Serial(
                port=port,
                baudrate=baud_rate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=1.0,
            )
            logger.info("Serial port %s opened at %d baud.", port, baud_rate)
            self.connected.emit(port)
            return True
        except serial.SerialException as exc:
            logger.error("Failed to open port %s: %s", port, exc)
            self._serial = None
            return False

    def disconnect(self) -> None:
        """Close the active serial connection if one is open."""
        if self._serial and self._serial.is_open:
            try:
                self._serial.close()
                logger.info("Serial port closed.")
            except serial.SerialException as exc:
                logger.error("Error while closing port: %s", exc)
            finally:
                self._serial = None
                self.disconnected.emit()

    def is_connected(self) -> bool:
        """Return ``True`` if the serial port is currently open."""
        return self._serial is not None and self._serial.is_open

    # ------------------------------------------------------------------
    # Data transmission
    # ------------------------------------------------------------------

    def send_json(self, data: dict) -> bool:
        """
        Serialise *data* to a JSON string and transmit it over serial.

        The message is encoded as UTF-8 and terminated with a newline byte
        (``0x0A``) so the ESP32 firmware can use line-based reading.

        Parameters
        ----------
        data:
            A JSON-serialisable dictionary.

        Returns
        -------
        bool
            ``True`` on success.
        """
        if not self.is_connected():
            self.send_error.emit("Cannot send: no active serial connection.")
            return False

        try:
            payload = json.dumps(data, separators=(",", ":")) + "\n"
            self._serial.write(payload.encode("utf-8"))
            self._serial.flush()
            logger.debug("JSON payload sent (%d bytes).", len(payload))
            return True
        except (serial.SerialException, TypeError, ValueError) as exc:
            error_msg = f"send_json failed: {exc}"
            logger.error(error_msg)
            self.send_error.emit(error_msg)
            return False

    def send_bytes(self, data: bytes) -> bool:
        """
        Transmit raw bytes over serial.

        Use this method for binary protocol frames where JSON overhead is
        undesirable.

        Parameters
        ----------
        data:
            Raw byte sequence to send.

        Returns
        -------
        bool
            ``True`` on success.
        """
        if not self.is_connected():
            self.send_error.emit("Cannot send: no active serial connection.")
            return False

        try:
            self._serial.write(data)
            self._serial.flush()
            logger.debug("Raw bytes sent (%d bytes).", len(data))
            return True
        except serial.SerialException as exc:
            error_msg = f"send_bytes failed: {exc}"
            logger.error(error_msg)
            self.send_error.emit(error_msg)
            return False
