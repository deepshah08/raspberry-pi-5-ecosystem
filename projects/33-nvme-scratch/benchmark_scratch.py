import os
import time
import json
import random
from pathlib import Path
from typing import Dict, Any


class BenchmarkScratch:
    def __init__(self, target_dir: str = "/volume2/scratch/benchmark_tmp"):
        self.target_dir = Path(target_dir)
        self.block_size_seq = 1024 * 1024  # 1MB
        self.block_size_rand = 4096        # 4KB

    def setup(self):
        self.target_dir.mkdir(parents=True, exist_ok=True)

    def teardown(self):
        if self.target_dir.exists():
            for f in self.target_dir.glob("*"):
                f.unlink()
            self.target_dir.rmdir()

    def measure_sequential_write(self, file_size_mb: int = 100) -> float:
        """Measures sequential write throughput in MB/s"""
        file_path = self.target_dir / "seq_write.tmp"
        data = bytearray(os.urandom(self.block_size_seq))

        start_time = time.time()
        with open(file_path, "wb") as f:
            for _ in range(file_size_mb):
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
        end_time = time.time()

        duration = end_time - start_time
        throughput = file_size_mb / duration if duration > 0 else 0
        return throughput

    def measure_sequential_read(self, file_size_mb: int = 100) -> float:
        """Measures sequential read throughput in MB/s"""
        file_path = self.target_dir / "seq_write.tmp"
        if not file_path.exists():
            self.measure_sequential_write(file_size_mb)

        start_time = time.time()
        with open(file_path, "rb") as f:
            while f.read(self.block_size_seq):
                pass
        end_time = time.time()

        duration = end_time - start_time
        throughput = file_size_mb / duration if duration > 0 else 0
        return throughput

    def measure_random_iops_and_latency(self, file_size_mb: int = 10, iterations: int = 1000) -> Dict[str, float]:
        """Measures random 4K IOPS and average latency in ms"""
        file_path = self.target_dir / "rand_io.tmp"
        total_size = file_size_mb * 1024 * 1024

        # Pre-allocate file
        with open(file_path, "wb") as f:
            f.truncate(total_size)

        max_offset = total_size - self.block_size_rand
        data = bytearray(os.urandom(self.block_size_rand))

        start_time = time.time()
        with open(file_path, "r+b") as f:
            for _ in range(iterations):
                offset = random.randint(0, max_offset)
                f.seek(offset)
                # Randomly choose read or write (50/50)
                if random.random() > 0.5:
                    f.write(data)
                else:
                    f.read(self.block_size_rand)
        end_time = time.time()

        duration = end_time - start_time
        iops = iterations / duration if duration > 0 else 0
        latency_ms = (duration / iterations) * 1000 if iterations > 0 else 0

        return {
            "iops": iops,
            "latency_ms": latency_ms
        }

    def generate_json_report(self, results: Dict[str, Any], output_path: str = "benchmark_results.json"):
        with open(output_path, "w") as f:
            json.dump(results, f, indent=4)
        print(f"JSON report saved to {output_path}")

    def generate_markdown_report(self, results: Dict[str, Any], output_path: str = "benchmark_results.md"):
        md_content = f"""# NVMe Scratch Disk Benchmark Results

| Metric | Value |
|--------|-------|
| Sequential Write | {results['sequential_write_mbps']} MB/s |
| Sequential Read | {results['sequential_read_mbps']} MB/s |
| Random 4K IOPS | {results['random_4k_iops']} IOPS |
| Average Latency | {results['average_latency_ms']} ms |
"""
        with open(output_path, "w") as f:
            f.write(md_content)
        print(f"Markdown report saved to {output_path}")

    def run_all_benchmarks(self) -> Dict[str, Any]:
        self.setup()
        print("Running sequential write benchmark...")
        seq_write = self.measure_sequential_write()
        print("Running sequential read benchmark...")
        seq_read = self.measure_sequential_read()
        print("Running random IOPS benchmark...")
        rand_io = self.measure_random_iops_and_latency()
        self.teardown()

        results = {
            "sequential_write_mbps": round(seq_write, 2),
            "sequential_read_mbps": round(seq_read, 2),
            "random_4k_iops": round(rand_io["iops"], 2),
            "average_latency_ms": round(rand_io["latency_ms"], 2)
        }

        self.generate_json_report(results)
        self.generate_markdown_report(results)

        return results

if __name__ == "__main__":
    benchmark = BenchmarkScratch()
    results = benchmark.run_all_benchmarks()
    print("Benchmark Results:", results)
