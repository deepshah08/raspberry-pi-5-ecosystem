import unittest
from scripts.pi5_health_check import parse_cpu_temp, parse_meminfo, parse_throttled, parse_df

class TestPi5HealthCheck(unittest.TestCase):
    def test_parse_cpu_temp_vcgencmd(self):
        output = "temp=45.3'C"
        self.assertEqual(parse_cpu_temp(output), 45.3)

    def test_parse_cpu_temp_sysfs(self):
        output = "45300"
        self.assertEqual(parse_cpu_temp(output), 45.3)

    def test_parse_cpu_temp_invalid(self):
        output = "invalid"
        self.assertEqual(parse_cpu_temp(output), 0.0)

    def test_parse_meminfo(self):
        output = """MemTotal:        8096240 kB
MemFree:         4865180 kB
MemAvailable:    6925180 kB
Buffers:          357184 kB
Cached:          1811800 kB
SwapCached:            0 kB
"""
        result = parse_meminfo(output)
        self.assertEqual(result["total_kb"], 8096240)
        self.assertEqual(result["available_kb"], 6925180)
        used = 8096240 - 6925180
        self.assertEqual(result["used_kb"], used)
        expected_percent = round((used / 8096240) * 100, 2)
        self.assertEqual(result["percent_used"], expected_percent)

    def test_parse_meminfo_empty(self):
        output = ""
        result = parse_meminfo(output)
        self.assertEqual(result["total_kb"], 0)
        self.assertEqual(result["available_kb"], 0)
        self.assertEqual(result["used_kb"], 0)
        self.assertEqual(result["percent_used"], 0.0)

    def test_parse_throttled(self):
        output = "throttled=0x50000"
        result = parse_throttled(output)
        self.assertEqual(result["raw"], "0x50000")
        self.assertFalse(result["currently_throttled"])
        self.assertTrue(result["under_voltage_occurred"])
        self.assertTrue(result["throttling_occurred"])
        self.assertFalse(result["soft_temperature_limit_occurred"])

    def test_parse_throttled_currently_throttled(self):
        output = "throttled=0x50005"
        result = parse_throttled(output)
        self.assertTrue(result["under_voltage_detected"])
        self.assertTrue(result["currently_throttled"])
        self.assertTrue(result["under_voltage_occurred"])
        self.assertTrue(result["throttling_occurred"])

    def test_parse_throttled_zero(self):
        output = "throttled=0x0"
        result = parse_throttled(output)
        self.assertEqual(result["raw"], "0x0")
        self.assertFalse(result["under_voltage_detected"])
        self.assertFalse(result["currently_throttled"])
        self.assertFalse(result["under_voltage_occurred"])
        self.assertFalse(result["throttling_occurred"])

    def test_parse_throttled_invalid(self):
        output = "invalid"
        result = parse_throttled(output)
        self.assertEqual(result["raw"], "0x0")

    def test_parse_df(self):
        output = """Filesystem      1K-blocks    Used Available Use% Mounted on
udev              3885024       0   3885024   0% /dev
tmpfs              809624    2272    807352   1% /run
/dev/nvme0n1p2  244030632 8652316 222907404   4% /
tmpfs             4048120       0   4048120   0% /dev/shm
tmpfs                5120      16      5104   1% /run/lock
/dev/nvme0n1p1     523248  154212    369036  30% /boot/firmware
tmpfs              809624     104    809520   1% /run/user/1000
"""
        result = parse_df(output)
        
        # /dev/nvme0n1p2 is mounted on /
        self.assertIn("/", result)
        self.assertEqual(result["/"]["filesystem"], "/dev/nvme0n1p2")
        self.assertEqual(result["/"]["percent_used"], 4.0)

        # /dev/nvme0n1p1 is mounted on /boot/firmware
        self.assertIn("/boot/firmware", result)
        self.assertEqual(result["/boot/firmware"]["filesystem"], "/dev/nvme0n1p1")
        self.assertEqual(result["/boot/firmware"]["percent_used"], 30.0)
        
        # Ensure non-monitored ones like tmpfs are omitted if not /
        self.assertNotIn("/dev", result)
        self.assertNotIn("/run", result)

if __name__ == '__main__':
    unittest.main()
