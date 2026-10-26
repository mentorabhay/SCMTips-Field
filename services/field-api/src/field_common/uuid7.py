"""RFC 9562 UUIDv7 Generator with 48-bit millisecond timestamp and 12-bit monotonic counter.

Task T1.016 / FR1.014 / Property PR1.11.
"""

import os
import threading
import time
import uuid

_lock = threading.Lock()
_last_v7_timestamp_ms = 0
_v7_counter = 0


def uuid7() -> uuid.UUID:
    """Generate a 128-bit RFC 9562 UUIDv7 with strictly monotonic sequencing."""
    global _last_v7_timestamp_ms, _v7_counter

    with _lock:
        now_ms = int(time.time() * 1000)

        if now_ms > _last_v7_timestamp_ms:
            _last_v7_timestamp_ms = now_ms
            # 12-bit counter initialized with 0 to 4095 range
            _v7_counter = int.from_bytes(os.urandom(2), "big") & 0x0FFF
        else:
            # Monotonic increment within the same millisecond
            _v7_counter = (_v7_counter + 1) & 0x0FFF
            if _v7_counter == 0:
                # Counter overflowed in the same millisecond, increment simulated timestamp
                _last_v7_timestamp_ms += 1

        ts_ms = _last_v7_timestamp_ms
        counter = _v7_counter

    # 48-bit unix timestamp in ms
    time_high = (ts_ms >> 16) & 0xFFFFFFFF
    time_mid = ts_ms & 0xFFFF

    # 12-bit counter placed into rand_a with 4-bit version 7
    ver_and_counter = (0x7 << 12) | (counter & 0x0FFF)

    # 62-bit rand_b with 2-bit variant 10
    rand_b_bytes = os.urandom(8)
    rand_b_int = int.from_bytes(rand_b_bytes, "big")
    var_and_rand = (0x2 << 62) | (rand_b_int & 0x3FFFFFFFFFFFFFFF)

    raw_int = (time_high << 96) | (time_mid << 80) | (ver_and_counter << 64) | var_and_rand

    return uuid.UUID(int=raw_int)


def uuid7_str() -> str:
    """Return UUIDv7 as standard 36-character hyphenated string."""
    return str(uuid7())
