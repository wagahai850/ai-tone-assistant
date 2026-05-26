"""Fractal Audio MIDI communication layer (device-agnostic singleton)."""

import mido
import time
import threading
from dataclasses import dataclass
from typing import Optional


@dataclass
class DeviceConfig:
    """Configuration for a specific Fractal Audio device."""
    name: str           # Human-readable name
    model_id: int       # SysEx model identifier
    port_name: str      # MIDI port name (as seen by OS) — Mac default
    port_out: str = ""  # Windows OUT port name (if different from port_name)
    port_in: str = ""   # Windows IN port name (if different from port_name)


# Known Fractal devices
DEVICES = {
    "fm9": DeviceConfig(
        name="FM9", model_id=0x12, port_name="FM9",
        port_out="FM9 MIDI Out 1", port_in="FM9 MIDI In 0",
    ),
    "axe3": DeviceConfig(
        name="Axe-Fx III", model_id=0x10, port_name="Axe-Fx III",
        port_out="Axe-Fx III MIDI Out 1", port_in="Axe-Fx III MIDI In 0",
    ),
    "fm3": DeviceConfig(
        name="FM3", model_id=0x11, port_name="FM3",
        port_out="FM3 MIDI Out 1", port_in="FM3 MIDI In 0",
    ),
}


class FractalMidi:
    """Singleton class managing MIDI communication with a Fractal Audio device."""

    _instance: Optional["FractalMidi"] = None
    _lock = threading.Lock()

    MANUFACTURER_ID = [0x00, 0x01, 0x74]

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._outport: Optional[mido.ports.BaseOutput] = None
        self._inport: Optional[mido.ports.BaseInput] = None
        self._device: Optional[DeviceConfig] = None
        self._midi_lock = threading.Lock()
        self._last_block_select: Optional[list[int]] = None

    def configure(self, device_key: str):
        """Set the target device. Must be called before connect()."""
        if device_key not in DEVICES:
            raise ValueError(f"Unknown device '{device_key}'. Available: {list(DEVICES.keys())}")
        self._device = DEVICES[device_key]

    @property
    def device(self) -> Optional[DeviceConfig]:
        return self._device

    @property
    def model_id(self) -> int:
        if not self._device:
            raise RuntimeError("Device not configured. Call configure() first.")
        return self._device.model_id

    @property
    def connected(self) -> bool:
        return self._outport is not None and self._inport is not None

    def connect(self, port_name: Optional[str] = None) -> bool:
        """Open MIDI ports. Auto-detects platform-specific port names."""
        with self._midi_lock:
            if self.connected:
                return True
            if not self._device:
                raise RuntimeError("Device not configured. Call configure() first.")

            available_out = mido.get_output_names()
            available_in = mido.get_input_names()

            if port_name:
                # Explicit port name: use for both in/out (Mac style)
                out_name = port_name
                in_name = port_name
            else:
                # Auto-detect: try Mac name first, then Windows names
                if self._device.port_name in available_out:
                    out_name = self._device.port_name
                    in_name = self._device.port_name
                elif self._device.port_out in available_out:
                    out_name = self._device.port_out
                    in_name = self._device.port_in
                else:
                    # Fuzzy match: find any port containing device name
                    dev_lower = self._device.name.lower()
                    out_matches = [p for p in available_out if dev_lower in p.lower()]
                    in_matches = [p for p in available_in if dev_lower in p.lower()]
                    if out_matches and in_matches:
                        out_name = out_matches[0]
                        in_name = in_matches[0]
                    else:
                        raise ConnectionError(
                            f"Cannot find MIDI ports for {self._device.name}. "
                            f"Available OUT: {available_out}, IN: {available_in}"
                        )

            try:
                self._outport = mido.open_output(out_name)
                self._inport = mido.open_input(in_name)
                time.sleep(0.2)
                while self._inport.poll():
                    pass
                return True
            except Exception as e:
                self._outport = None
                self._inport = None
                raise ConnectionError(f"Failed to connect to {self._device.name} (out={out_name}, in={in_name}): {e}")

    def disconnect(self):
        """Close MIDI ports."""
        with self._midi_lock:
            if self._outport:
                self._outport.close()
                self._outport = None
            if self._inport:
                self._inport.close()
                self._inport = None

    def _checksum(self, *data_bytes: int) -> int:
        """Calculate Fractal checksum: XOR(model_id, data...) ^ 0x05 & 0x7F."""
        cs = self.model_id
        for b in data_bytes:
            cs ^= b
        cs ^= 0x05
        return cs & 0x7F

    def _send_sysex(self, data: list[int]):
        """Send a SysEx message (data after manufacturer + model prefix)."""
        if not self.connected:
            raise ConnectionError(f"Not connected to {self._device.name}")
        full_data = self.MANUFACTURER_ID + [self.model_id] + data
        self._outport.send(mido.Message("sysex", data=full_data))

    def _flush_input(self):
        """Flush all pending input messages."""
        count = 0
        while True:
            msg = self._inport.poll()
            if msg is None:
                break
            count += 1
        # Double flush with small delay to catch stragglers
        if count > 0:
            time.sleep(0.1)
            while self._inport.poll():
                pass

    def _receive_sysex(self, timeout: float = 2.0) -> list[mido.Message]:
        """Receive all SysEx messages within timeout."""
        messages = []
        deadline = time.time() + timeout
        while time.time() < deadline:
            msg = self._inport.poll()
            if msg is None:
                if messages:
                    time.sleep(0.05)
                    msg = self._inport.poll()
                    if msg is None:
                        break
                else:
                    time.sleep(0.01)
                    continue
            if msg.type == "sysex":
                messages.append(msg)
        return messages

    def set_scene(self, scene: int) -> bool:
        """Set scene (0-based: 0=Scene1, 1=Scene2, ...)."""
        with self._midi_lock:
            func = 0x0C
            cs = self._checksum(func, scene)
            self._send_sysex([func, scene, cs])
            time.sleep(0.1)
            return True

    def set_bypass(self, effect_id: int, bypassed: bool) -> bool:
        """Set effect bypass state."""
        with self._midi_lock:
            func = 0x0A
            id_lo = effect_id & 0x7F
            id_hi = (effect_id >> 7) & 0x7F
            dd = 1 if bypassed else 0
            cs = self._checksum(func, id_lo, id_hi, dd)
            self._send_sysex([func, id_lo, id_hi, dd, cs])
            time.sleep(0.1)
            return True

    def get_block_data(self, block_id: int) -> list[list[int]]:
        """GET block data (func 0x1F). Returns list of chunk data arrays.
        Also stores the block_select message for use in put_block_data."""
        with self._midi_lock:
            self._flush_input()
            func = 0x1F
            id_lo = block_id & 0x7F
            id_hi = (block_id >> 7) & 0x7F
            cs = self._checksum(func, id_lo, id_hi)
            self._send_sysex([func, id_lo, id_hi, cs])
            time.sleep(0.5)

            # Collect responses: func 0x74 (block select) and func 0x75 (data chunks)
            self._last_block_select = None
            chunks = []
            deadline = time.time() + 3.0
            while time.time() < deadline:
                msg = self._inport.poll()
                if msg is None:
                    if chunks:
                        time.sleep(0.1)
                        msg = self._inport.poll()
                        if msg is None:
                            break
                    else:
                        time.sleep(0.02)
                    continue
                if msg.type == "sysex" and len(msg.data) >= 5:
                    if msg.data[4] == 0x75:
                        chunks.append(list(msg.data))
                    elif msg.data[4] == 0x74:
                        self._last_block_select = list(msg.data)
            return chunks

    def put_block_data(self, block_id: int, chunks: list[list[int]]) -> bool:
        """PUT block data using the BLOCK SELECT from last GET response."""
        with self._midi_lock:
            # Use stored block_select from GET, or construct a basic one
            if self._last_block_select:
                self._outport.send(mido.Message("sysex", data=self._last_block_select))
            else:
                # Fallback: basic block select (works for Amp/Drive only)
                self._send_sysex([0x74, block_id & 0x7F, (block_id >> 7) & 0x7F, 0x4C, 0x04, 0x11])
            time.sleep(0.02)

            # PRESET DATA chunks (func 0x75)
            for chunk in chunks:
                self._outport.send(mido.Message("sysex", data=chunk))
                time.sleep(0.02)

            # COMMIT (func 0x76)
            cs_commit = self._checksum(0x76)
            self._send_sysex([0x76, cs_commit])
            time.sleep(0.3)

            self._flush_input()
            return True

    def _send_sub09(self, block_id: int, param: int, value_id: int) -> bool:
        """Send sub=0x09 command (enum/model/IR selection).
        Used for Amp Type, Drive Type, Cab IR, etc.
        Supports block_id > 0x7F via 2-byte encoding."""
        with self._midi_lock:
            id_lo = value_id & 0x7F
            id_hi = (value_id >> 7) & 0x7F
            id_msb = (value_id >> 14) & 0x7F

            block_lo = block_id & 0x7F
            block_hi = (block_id >> 7) & 0x7F
            param_lo = param & 0x7F
            param_hi = (param >> 7) & 0x7F

            payload = [0x01, 0x09, 0x00, block_lo, block_hi, param_lo, param_hi,
                       0x00, 0x00, id_lo, id_hi, id_msb, 0x00, 0x00, 0x00, 0x00]
            cs = self.model_id
            for b in payload:
                cs ^= b
            cs = (cs ^ 0x05) & 0x7F
            payload.append(cs)

            self._send_sysex(payload)
            time.sleep(0.5)
            self._flush_input()
            return True

    def set_amp_type(self, type_id: int, block_id: int = 0x3A) -> bool:
        """Set Amp Type using sub=0x09, param=0x0A."""
        return self._send_sub09(block_id, 0x0A, type_id)

    def set_drive_type(self, type_id: int, block_id: int = 0x76) -> bool:
        """Set Drive Type using sub=0x09, param=0x0A."""
        return self._send_sub09(block_id, 0x0A, type_id)

    def set_cab_ir(self, ir_id: int, block_id: int = 0x3E) -> bool:
        """Set Cab IR using sub=0x09, param=0x04.
        ir_id is the 21-bit IR identifier (from Factory/User bank)."""
        return self._send_sub09(block_id, 0x04, ir_id)

    def set_param_value(self, block_id: int, param_id: int, value: float, max_value: float,
                       channel: int = 0, raw_float: bool = False) -> bool:
        """Set a parameter value using sub=0x09 with IEEE 754 float encoding.

        Args:
            block_id: Block ID (e.g., 0x3A for Amp 1)
            param_id: Parameter ID (e.g., 0x0B for Gain)
            value: Display value (e.g., 5.0 for Gain=5)
            max_value: Maximum display value (e.g., 10.0 for Gain range 0-10)
            channel: Target channel (0=A, 1=B, 2=C, 3=D). Encoded as channel * 0x20.
            raw_float: If True, send value as-is (no normalization/clamping).
                       Used for frequency params where FM9 expects Hz directly.
        """
        import struct
        if raw_float:
            normalized = value
        else:
            normalized = value / max_value if max_value != 0 else 0.0
            normalized = max(0.0, min(1.0, normalized))
        raw32 = struct.unpack('I', struct.pack('f', normalized))[0]
        d = [
            raw32 & 0x7F,
            (raw32 >> 7) & 0x7F,
            (raw32 >> 14) & 0x7F,
            (raw32 >> 21) & 0x7F,
            (raw32 >> 28) & 0x7F,
        ]

        channel_byte = (channel & 0x03) * 0x20

        # 2-byte encoding for block_id and param_id (7-bit SysEx safe)
        block_lo = block_id & 0x7F
        block_hi = (block_id >> 7) & 0x7F
        param_lo = param_id & 0x7F
        param_hi = (param_id >> 7) & 0x7F

        with self._midi_lock:
            payload = [0x01, 0x09, 0x00, block_lo, block_hi, param_lo, param_hi,
                       d[0], d[1], d[2], d[3], d[4], 0x00, 0x00, channel_byte, 0x00]
            cs = self.model_id
            for b in payload:
                cs ^= b
            cs = (cs ^ 0x05) & 0x7F
            payload.append(cs)

            self._send_sysex(payload)
            time.sleep(0.1)
            self._flush_input()
            return True

    def set_channel(self, block_id: int, channel: int) -> bool:
        """Set block channel (0=A, 1=B, 2=C, 3=D) using sub=0x16."""
        with self._midi_lock:
            payload = [0x01, 0x16, 0x00, block_id, 0x00, 0x00, 0x00,
                       channel, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]
            cs = self.model_id
            for b in payload:
                cs ^= b
            cs = (cs ^ 0x05) & 0x7F
            payload.append(cs)

            self._send_sysex(payload)
            time.sleep(0.3)
            self._flush_input()
            return True

    def get_status_dump(self) -> dict[int, dict]:
        """Get STATUS DUMP (func 0x13). Returns {effect_id: {bypass, channel}}."""
        with self._midi_lock:
            self._flush_input()
            cs = self._checksum(0x13)
            self._send_sysex([0x13, cs])
            time.sleep(0.5)

            messages = self._receive_sysex(timeout=1.0)
            status = {}
            for msg in messages:
                if len(msg.data) >= 5 and msg.data[4] == 0x13:
                    data = list(msg.data[5:-1])
                    for i in range(0, len(data) - 2, 3):
                        id_lo = data[i]
                        id_hi = data[i + 1]
                        dd = data[i + 2]
                        effect_id = id_lo | (id_hi << 7)
                        status[effect_id] = {
                            "bypass": bool(dd & 0x01),
                            "channel": (dd >> 1) & 0x07,
                        }
            return status

    def _send_param_msg(self, sub: int, block_id: int, data_bytes: list[int]) -> bool:
        """Send a generic func=0x01 PARAM_MSG with given sub, block, and data.
        data_bytes fills positions [7:16] (9 bytes max, zero-padded).
        Total payload = 16 bytes + checksum = 17 bytes → 23-byte SysEx message."""
        with self._midi_lock:
            data = data_bytes[:9] + [0] * (9 - len(data_bytes[:9]))
            payload = [0x01, sub, 0x00, block_id, 0x00, 0x00, 0x00] + data
            cs = self.model_id
            for b in payload:
                cs ^= b
            cs = (cs ^ 0x05) & 0x7F
            payload.append(cs)
            self._send_sysex(payload)
            time.sleep(0.3)
            self._flush_input()
            return True

    def store_preset(self, preset_number: int) -> bool:
        """Store (save) current preset to given preset number (0-based)."""
        lo = preset_number & 0x7F
        hi = (preset_number >> 7) & 0x7F
        return self._send_param_msg(0x26, 0x00, [lo, hi, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])

    def change_preset(self, preset_number: int) -> bool:
        """Switch to a different preset (0-based)."""
        lo = preset_number & 0x7F
        hi = (preset_number >> 7) & 0x7F
        return self._send_param_msg(0x27, 0x00, [lo, hi, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])

    def get_preset_info(self) -> dict:
        """Get current preset number and name using func=0x0D.

        Protocol (confirmed 2026-05-26):
        - Request (with preset number): F0 00 01 74 12 0D [lo] [hi] [cs] F7
          Response: [0x0D] [preset_lo] [preset_hi] [name:32 ASCII] [0x00] [cs]
          Returns the specified preset's name.
        - Special case: sending lo=0x7F, hi=0x7F (invalid preset 16383)
          causes FM9 to return the CURRENT preset number and name.

        Returns {'preset_number': int, 'name': str} or empty dict on failure.
        """
        with self._midi_lock:
            self._flush_input()

            # Query current preset: send 0x7F,0x7F (magic value = "give me current")
            lo = 0x7F
            hi = 0x7F
            cs = self._checksum(0x0D, lo, hi)
            self._send_sysex([0x0D, lo, hi, cs])
            time.sleep(0.3)

            messages = self._receive_sysex(timeout=1.0)
            for msg in messages:
                if len(msg.data) >= 9 and msg.data[4] == 0x0D:
                    # Response: [mfr:3][model:1][func:1][lo:1][hi:1][name:32][0x00][cs:1]
                    preset_number = msg.data[5] | (msg.data[6] << 7)
                    name_bytes = list(msg.data[7:-1])  # exclude checksum
                    name = ''.join(chr(b) for b in name_bytes if 32 <= b < 127).rstrip()
                    return {"preset_number": preset_number, "name": name}

            return {}


    def add_block(self, block_id: int) -> bool:
        """Add a block to the current preset layout.
        block_id: e.g., 0x3A=Amp1, 0x76=Drive1, 0x3E=Cab1, 0x46=Delay1, 0x42=Reverb1."""
        with self._midi_lock:
            # sub=0x30: layout operation start
            # data[0] seems to be an operation token (observed: 0x12, 0x19)
            # Using 0x19 based on block_add_amp capture
            op_id = 0x19
            payload_30 = [0x01, 0x30, 0x00, 0x00, 0x00, 0x00, 0x00,
                          op_id, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]
            cs = self.model_id
            for b in payload_30:
                cs ^= b
            cs = (cs ^ 0x05) & 0x7F
            payload_30.append(cs)
            self._send_sysex(payload_30)
            time.sleep(0.1)

            # sub=0x32: block add declaration
            payload_32 = [0x01, 0x32, 0x00, block_id, 0x00, 0x00, 0x00,
                          op_id, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]
            cs = self.model_id
            for b in payload_32:
                cs ^= b
            cs = (cs ^ 0x05) & 0x7F
            payload_32.append(cs)
            self._send_sysex(payload_32)
            time.sleep(0.5)

            self._flush_input()
            return True

    @staticmethod
    def encode_preset_name(name: str, max_len: int = 32) -> list[int]:
        """Encode preset name to 7-bit packed MIDI bytes (MSB-first bitstream)."""
        name = name.ljust(max_len, ' ')[:max_len]
        bits = ''.join(f'{ord(c):08b}' for c in name)
        result = []
        for i in range(0, len(bits), 7):
            chunk = bits[i:i+7].ljust(7, '0')
            result.append(int(chunk, 2))
        return result

    def set_preset_name(self, preset_number: int, name: str) -> bool:
        """Set preset name (immediately reflected on device)."""
        with self._midi_lock:
            lo = preset_number & 0x7F
            hi = (preset_number >> 7) & 0x7F
            name_bytes = self.encode_preset_name(name)

            # Build 60-byte message:
            # F0 [mfr+model=4] [payload=54] F7
            # payload: 01 28 00 00 00 00 00 [lo hi] 00 00 00 00 00 20 00 [name_37bytes] [cs]
            payload = [0x01, 0x28, 0x00, 0x00, 0x00, 0x00, 0x00,
                       lo, hi, 0x00, 0x00, 0x00, 0x00, 0x00, 0x20, 0x00] + name_bytes
            # Pad/truncate to 53 bytes (+ cs = 54)
            while len(payload) < 53:
                payload.append(0x00)
            payload = payload[:53]

            cs = self.model_id
            for b in payload:
                cs ^= b
            cs = (cs ^ 0x05) & 0x7F
            payload.append(cs)

            self._send_sysex(payload)
            time.sleep(0.3)
            self._flush_input()
            return True

    # --- Grid / Routing Operations ---

    @staticmethod
    def grid_pos(row: int, col: int) -> int:
        """Encode grid position: col_0based * 6 + row_0based.
        FM9 grid: 5 rows (0-4) x 14 cols (0-13)."""
        return col * 6 + row

    @staticmethod
    def grid_decode(pos: int) -> tuple[int, int]:
        """Decode grid position to (row, col)."""
        return pos % 6, pos // 6

    def _send_layout_msg(self, sub: int, block_id: int, p: list[int], d: list[int]) -> bool:
        """Send a 23-byte func=0x01 layout message."""
        with self._midi_lock:
            p_padded = (p + [0, 0, 0])[:3]
            d_padded = (d + [0] * 9)[:9]
            payload = [0x01, sub, 0x00, block_id] + p_padded + d_padded
            cs = self.model_id
            for b in payload:
                cs ^= b
            cs = (cs ^ 0x05) & 0x7F
            payload.append(cs)
            self._send_sysex(payload)
            time.sleep(0.02)
            return True

    def _send_layout_msg_26byte(self, sub: int, block_id: int, p: list[int], d: list[int]) -> bool:
        """Send a 26-byte (mido data) func=0x01 message (used for cable connect/disconnect sub=0x35)."""
        with self._midi_lock:
            p_padded = (p + [0, 0, 0])[:3]
            d_padded = (d + [0] * 14)[:14]
            payload = [0x01, sub, 0x00, block_id] + p_padded + d_padded
            cs = self.model_id
            for b in payload:
                cs ^= b
            cs = (cs ^ 0x05) & 0x7F
            payload.append(cs)
            self._send_sysex(payload)
            time.sleep(0.02)
            return True

    def add_block_at(self, block_id: int, row: int, col: int) -> bool:
        """Add a block at a specific grid position.
        Args:
            block_id: Block type ID (e.g., 0x3A=Amp1, 0x76=Drive1, 0x92=Gate1)
                      Supports block_id > 0x7F via 2-byte encoding.
            row: Grid row (0-4)
            col: Grid column (0-13)
        """
        pos = self.grid_pos(row, col)
        # Block ID encoding: split into 2 bytes for SysEx 7-bit compliance
        id_lo = block_id & 0x7F
        id_hi = (block_id >> 7) & 0x7F

        # Step 1: sub=0x30 — layout operation start
        self._send_layout_msg(0x30, 0x00, [0, 0, 0], [pos, 0, 0, 0, 0, 0, 0, 0, 0])
        # Step 2: sub=0x32 — block add (2-byte block_id in positions [3:5])
        with self._midi_lock:
            payload = [0x01, 0x32, 0x00, id_lo, id_hi, 0x00, 0x00,
                       pos, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]
            cs = self.model_id
            for b in payload:
                cs ^= b
            cs = (cs ^ 0x05) & 0x7F
            payload.append(cs)
            self._send_sysex(payload)
            time.sleep(0.1)
            self._flush_input()
        return True

    def delete_block_at(self, row: int, col: int) -> bool:
        """Delete the block at a specific grid position."""
        pos = self.grid_pos(row, col)
        self._send_layout_msg(0x30, 0x25, [0, 0, 0], [pos, 0, 0, 0, 0, 0, 0, 0, 0])
        self._send_layout_msg(0x33, 0x25, [0, 0, 0], [pos, 0, 0, 0, 0, 0, 0, 0, 0])
        time.sleep(0.1)
        with self._midi_lock:
            self._flush_input()
        return True

    def move_block(self, from_row: int, from_col: int, to_row: int, to_col: int) -> bool:
        """Move a block from one grid position to another.
        Movement is done step-by-step (1 cell at a time) using direction codes.
        """
        from_pos = self.grid_pos(from_row, from_col)
        self._send_layout_msg(0x30, 0x25, [0, 0, 0], [from_pos, 0, 0, 0, 0, 0, 0, 0, 0])

        col_diff = to_col - from_col
        row_diff = to_row - from_row

        if col_diff != 0:
            direction = 0x01 if col_diff > 0 else 0x00
            for _ in range(abs(col_diff)):
                self._send_layout_msg(0x36, 0x25, [0, 0, 0], [direction, 0, 0, 0, 0, 0, 0, 0, 0])

        if row_diff != 0:
            direction = 0x03 if row_diff > 0 else 0x02
            for _ in range(abs(row_diff)):
                self._send_layout_msg(0x36, 0x25, [0, 0, 0], [direction, 0, 0, 0, 0, 0, 0, 0, 0])

        time.sleep(0.05)
        with self._midi_lock:
            self._flush_input()
        return True

    def connect_adjacent(self, from_row: int, from_col: int, to_row: int, to_col: int) -> bool:
        """Connect two adjacent blocks with a cable.
        Uses the discovered coordinate encoding in d[9:12].
        Args: 0-based row/col for both endpoints.
        """
        from_pos = from_col * 6 + from_row
        to_pos = to_col * 6 + to_row
        d9 = from_pos >> 1
        d10 = (to_pos >> 2) | ((from_pos & 0x01) << 6)
        d11 = (to_pos & 0x03) << 5

        # sub=0x35, block=0x00(fixed), d[0]=0x01(connect), d[7]=0x02(fixed), d[9:12]=coords
        self._send_layout_msg_26byte(
            0x35, 0x00, [0, 0, 0],
            [0x01, 0, 0, 0, 0, 0, 0, 0x02, 0, d9, d10, d11, 0, 0]
        )
        return True

    def disconnect_adjacent(self, from_row: int, from_col: int, to_row: int, to_col: int) -> bool:
        """Disconnect two adjacent blocks (remove cable).
        Args: 0-based row/col for both endpoints.
        """
        from_pos = from_col * 6 + from_row
        to_pos = to_col * 6 + to_row
        d9 = from_pos >> 1
        d10 = (to_pos >> 2) | ((from_pos & 0x01) << 6)
        d11 = (to_pos & 0x03) << 5

        # sub=0x35, block=0x00(fixed), d[0]=0x02(disconnect), d[7]=0x02(fixed), d[9:12]=coords
        self._send_layout_msg_26byte(
            0x35, 0x00, [0, 0, 0],
            [0x02, 0, 0, 0, 0, 0, 0, 0x02, 0, d9, d10, d11, 0, 0]
        )
        return True

    def add_shunt_at(self, row: int, col: int, shunt_index: int = 0) -> bool:
        """Add a shunt block (cable routing placeholder) at a grid position.
        Used internally when connecting non-adjacent blocks.

        Args:
            row: Grid row (0-4)
            col: Grid column (0-13)
            shunt_index: Sequential index for this shunt (0, 1, 2, 3...).
                         FM9 requires each shunt in a batch to have a unique index.
        """
        pos = self.grid_pos(row, col)

        # Step 1: sub=0x30 — layout operation start
        self._send_layout_msg(0x30, 0x00, [0, 0, 0], [pos, 0, 0, 0, 0, 0, 0, 0, 0])

        # Step 2: sub=0x32 — shunt add
        # byte[3] = shunt_index (increments for each shunt in a batch)
        # byte[4] = 0x08 (shunt flag)
        with self._midi_lock:
            payload2 = [0x01, 0x32, 0x00, shunt_index, 0x08, 0x00, 0x00,
                        pos, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]
            cs = self.model_id
            for b in payload2:
                cs ^= b
            cs = (cs ^ 0x05) & 0x7F
            payload2.append(cs)
            self._send_sysex(payload2)
            time.sleep(0.1)
            self._flush_input()
        return True

    def connect_blocks(self, from_row: int, from_col: int, to_row: int, to_col: int) -> bool:
        """Connect two blocks with a cable, placing shunts in between if needed.
        Supports same-row and cross-row connections.

        Routing strategy:
        - Same row: shunts placed horizontally between from_col and to_col.
        - Cross row: first cable crosses rows (from_row,from_col → to_row,from_col+1),
          then shunts extend horizontally on to_row toward to_col.
          If same column, direct cross-row cable (no shunts).

        from_col must be < to_col (unless same-column cross-row).
        """
        if from_row == to_row and from_col >= to_col:
            raise ValueError("from_col must be < to_col for same-row connections.")
        if from_row != to_row and from_col > to_col:
            raise ValueError("from_col must be <= to_col for cross-row connections.")

        # Determine next shunt index by reading current grid
        raw_grid = self.read_grid_raw()
        max_shunt_idx = -1
        for row_data in raw_grid:
            for cell in row_data:
                raw = cell["raw_32"]
                byte2 = (raw >> 16) & 0xFF
                if byte2 == 0x08:  # is shunt
                    bid = cell["block_id"]
                    if bid > max_shunt_idx:
                        max_shunt_idx = bid
        next_idx = max_shunt_idx + 1

        if from_row == to_row:
            # Same-row: shunts in intermediate columns
            shunt_cols = list(range(from_col + 1, to_col))
            for i, col in enumerate(shunt_cols):
                self.add_shunt_at(from_row, col, shunt_index=next_idx + i)
            for col in range(from_col, to_col):
                self.connect_adjacent(from_row, col, from_row, col + 1)
        elif from_col == to_col:
            # Same column, cross-row: direct cable, no shunts
            self.connect_adjacent(from_row, from_col, to_row, to_col)
        else:
            # Cross-row + cross-column:
            # Shunts on to_row from from_col+1 to to_col-1
            shunt_cols = list(range(from_col + 1, to_col))
            for i, col in enumerate(shunt_cols):
                self.add_shunt_at(to_row, col, shunt_index=next_idx + i)

            # First cable: cross rows (from_row,from_col) → (to_row,from_col+1)
            self.connect_adjacent(from_row, from_col, to_row, from_col + 1)

            # Remaining cables: horizontal on to_row
            for col in range(from_col + 1, to_col):
                self.connect_adjacent(to_row, col, to_row, col + 1)

        with self._midi_lock:
            self._flush_input()
        return True

    # --- Grid Reading ---

    # Grid decode constants (from RE session 2026-05-23)
    GRID_BASE_BIT = 46       # First cell starts at bit 46 in the grid region
    GRID_COL_STRIDE = 192    # Bits per column (6 internal rows × 32 bits)
    GRID_ROW_STRIDE = 32     # Bits per row
    GRID_ROWS = 5            # Visible rows
    GRID_COLS = 14           # Visible columns
    GRID_REGION_OFFSET = 11 + 350  # Offset in mido response data to grid region

    def read_grid(self) -> list[list[int]]:
        """Read the current grid layout from FM9 via sub=0x2E.

        Returns a 5×14 grid (rows × cols) where each cell contains the block_id
        (0 = empty cell, nonzero = block present).
        """
        # Send sub=0x2E query
        cs = self._checksum(0x01, 0x2E)
        query = self.MANUFACTURER_ID + [self._device.model_id, 0x01, 0x2E,
                 0x00, 0x00, 0x00, 0x00, 0x00,
                 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, cs]

        with self._midi_lock:
            self._flush_input()
            self._outport.send(mido.Message("sysex", data=query))
            time.sleep(1.0)

            # Collect the large response (>700 bytes)
            response = None
            deadline = time.time() + 3.0
            while time.time() < deadline:
                msg = self._inport.poll()
                if msg is None:
                    time.sleep(0.05)
                    continue
                if (msg.type == "sysex" and len(msg.data) > 700
                        and msg.data[4] == 0x01 and msg.data[5] == 0x2E):
                    response = list(msg.data)
                    break

        if not response:
            raise RuntimeError("No sub=0x2E response from device.")

        # Extract grid region (starts at offset 361 in mido data = 11 header + 350 pre-grid)
        grid_data = response[self.GRID_REGION_OFFSET:]
        if len(grid_data) < 392:
            raise RuntimeError(f"Grid region too short: {len(grid_data)} bytes (need 392).")

        # Decode each cell
        grid = [[0] * self.GRID_COLS for _ in range(self.GRID_ROWS)]

        for col in range(self.GRID_COLS):
            for row in range(self.GRID_ROWS):
                bit_offset = self.GRID_BASE_BIT + col * self.GRID_COL_STRIDE + row * self.GRID_ROW_STRIDE
                block_id = self._read_block_id_at_bit(grid_data, bit_offset)
                # Check for shunt: block_id=0 but block_type (bits 8-15) = 0x08
                if block_id == 0:
                    raw_32 = self._read_bits(grid_data, bit_offset, 32)
                    block_type = (raw_32 >> 8) & 0xFF
                    if block_type == 0x08:
                        # Shunt block — use a sentinel value to indicate presence
                        # Use 0x7F (127) as shunt marker in the simple grid view
                        grid[row][col] = 0x7F
                    else:
                        grid[row][col] = 0
                else:
                    grid[row][col] = block_id

        return grid

    def read_grid_raw(self) -> list[list[dict]]:
        """Read the current grid layout with full 32-bit cell data.

        Returns a 5×14 grid where each cell is a dict with:
        - block_id: 7-bit block identifier (0 = empty)
        - raw_32: full 32-bit cell value (for cable/flag analysis)
        """
        cs = self._checksum(0x01, 0x2E)
        query = self.MANUFACTURER_ID + [self._device.model_id, 0x01, 0x2E,
                 0x00, 0x00, 0x00, 0x00, 0x00,
                 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, cs]

        with self._midi_lock:
            self._flush_input()
            self._outport.send(mido.Message("sysex", data=query))
            time.sleep(1.0)

            response = None
            deadline = time.time() + 3.0
            while time.time() < deadline:
                msg = self._inport.poll()
                if msg is None:
                    time.sleep(0.05)
                    continue
                if (msg.type == "sysex" and len(msg.data) > 700
                        and msg.data[4] == 0x01 and msg.data[5] == 0x2E):
                    response = list(msg.data)
                    break

        if not response:
            raise RuntimeError("No sub=0x2E response from device.")

        grid_data = response[self.GRID_REGION_OFFSET:]
        if len(grid_data) < 392:
            raise RuntimeError(f"Grid region too short: {len(grid_data)} bytes (need 392).")

        grid = [[{"block_id": 0, "raw_32": 0} for _ in range(self.GRID_COLS)] for _ in range(self.GRID_ROWS)]

        for col in range(self.GRID_COLS):
            for row in range(self.GRID_ROWS):
                bit_offset = self.GRID_BASE_BIT + col * self.GRID_COL_STRIDE + row * self.GRID_ROW_STRIDE
                block_id = self._read_block_id_at_bit(grid_data, bit_offset)
                raw_32 = self._read_bits(grid_data, bit_offset, 32)
                grid[row][col] = {"block_id": block_id, "raw_32": raw_32}

        return grid

    @staticmethod
    def _read_bits(data: list[int], bit_offset: int, num_bits: int) -> int:
        """Read arbitrary number of bits from a 7-bit byte stream."""
        result = 0
        for i in range(num_bits):
            bit_pos = bit_offset + i
            byte_idx = bit_pos // 7
            bit_within = bit_pos % 7
            if byte_idx < len(data):
                bit_val = (data[byte_idx] >> (6 - bit_within)) & 1
                result = (result << 1) | bit_val
        return result

    @staticmethod
    def _read_block_id_at_bit(data: list[int], bit_offset: int) -> int:
        """Read 8 bits from a 7-bit byte stream at the given bit offset, then >> 1 to get block_id.
        
        Note: block_ids > 0x7F (e.g., Gate=0x92) will appear truncated because
        their stored value (block_id << 1) exceeds 8 bits. These need special handling.
        """
        byte_idx = bit_offset // 7
        bit_within_byte = bit_offset % 7

        if byte_idx + 1 >= len(data):
            return 0

        # We need 8 consecutive bits starting at bit_offset
        available_in_first = 7 - bit_within_byte

        first_byte = data[byte_idx]
        first_bits = first_byte & ((1 << available_in_first) - 1)

        bits_needed = 8 - available_in_first

        if bits_needed <= 0:
            value = (first_bits >> (-bits_needed)) & 0xFF
        elif bits_needed <= 7:
            second_byte = data[byte_idx + 1] if byte_idx + 1 < len(data) else 0
            second_bits = (second_byte >> (7 - bits_needed)) & ((1 << bits_needed) - 1)
            value = (first_bits << bits_needed) | second_bits
        else:
            second_byte = data[byte_idx + 1] if byte_idx + 1 < len(data) else 0
            remaining = bits_needed - 7
            third_byte = data[byte_idx + 2] if byte_idx + 2 < len(data) else 0
            third_bits = (third_byte >> (7 - remaining)) & ((1 << remaining) - 1)
            value = (first_bits << bits_needed) | (second_byte << remaining) | third_bits

        block_id = value >> 1
        return block_id
