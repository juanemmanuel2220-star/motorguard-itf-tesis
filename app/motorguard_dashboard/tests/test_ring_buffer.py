"""
Pruebas unitarias para NumPyRingBuffer.
"""

import numpy as np
import time
from motorguard_dashboard.core.ring_buffer import NumPyRingBuffer

def test_ring_buffer_basic():
    buf = NumPyRingBuffer(capacity=100)
    assert not buf.is_ready(50)
    
    # Push 30 samples
    c1 = np.ones((3, 30), dtype=np.float32)
    v1 = np.ones((2, 30), dtype=np.float32) * 120.0
    tot = buf.push(c1, v1)
    assert tot == 30
    assert not buf.is_ready(50)
    
    # Push 30 more samples
    c2 = np.ones((3, 30), dtype=np.float32) * 2.0
    v2 = np.ones((2, 30), dtype=np.float32) * 123.0
    tot = buf.push(c2, v2)
    assert tot == 60
    assert buf.is_ready(50)
    
    # Get last 40 samples
    curr, volt, t, end_idx = buf.get_latest_window(40)
    assert curr.shape == (3, 40)
    assert volt.shape == (2, 40)
    assert end_idx == 60
    # The last 30 samples should be 2.0, first 10 should be 1.0
    assert np.allclose(curr[0, :10], 1.0)
    assert np.allclose(curr[0, 10:], 2.0)
    print("test_ring_buffer_basic PASSED")

def test_ring_buffer_wrap_around():
    capacity = 100
    buf = NumPyRingBuffer(capacity=capacity)
    
    # Push sequence 0..149 across capacity
    total_samples = 150
    chunk_size = 25
    for i in range(0, total_samples, chunk_size):
        c = np.arange(i, i + chunk_size, dtype=np.float32).reshape(1, -1)
        c = np.repeat(c, 3, axis=0)
        v = np.zeros((2, chunk_size), dtype=np.float32)
        buf.push(c, v)
        
    assert buf._total_samples == 150
    # Retrieve last 50 samples: should be 100..149
    curr, volt, t, end_idx = buf.get_latest_window(50)
    expected = np.arange(100, 150, dtype=np.float32)
    assert np.allclose(curr[0], expected), f"Mismatch: {curr[0]} vs {expected}"
    assert end_idx == 150
    print("test_ring_buffer_wrap_around PASSED")

def test_ring_buffer_performance():
    capacity = 24000
    buf = NumPyRingBuffer(capacity=capacity)
    
    # Push 2400 samples (1 sec) 20 times (20 seconds worth of signal)
    c = np.random.randn(3, 1200).astype(np.float32)
    v = np.random.randn(2, 1200).astype(np.float32)
    
    start_t = time.perf_counter()
    for _ in range(40):
        buf.push(c, v)
        if buf.is_ready(2400):
            _ = buf.get_latest_window(2400)
    duration = time.perf_counter() - start_t
    print(f"40 cycles (20 sec equivalent signal) processed in: {duration*1000:.2f} ms")
    assert duration < 0.2, "RingBuffer too slow"
    print("test_ring_buffer_performance PASSED")

if __name__ == "__main__":
    test_ring_buffer_basic()
    test_ring_buffer_wrap_around()
    test_ring_buffer_performance()
