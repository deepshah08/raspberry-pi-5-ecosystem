import os
import time

class SMRBufferWriter:
    """
    A sequential batch buffer writer class that flushes data in configurable chunk sizes 
    with write rate throttling. Useful for protecting SMR (Shingled Magnetic Recording) 
    drives from IO freezes during small random writes.
    """
    def __init__(self, filepath, chunk_size_bytes=64 * 1024 * 1024, max_rate_mb_s=20.0):
        """
        :param filepath: Path to the file to write to.
        :param chunk_size_bytes: Size of chunks to buffer before flushing to disk.
        :param max_rate_mb_s: Maximum write rate in Megabytes per second. Set to 0 to disable throttling.
        """
        self.filepath = filepath
        self.chunk_size_bytes = chunk_size_bytes
        self.max_rate_bytes_s = max_rate_mb_s * 1024 * 1024 if max_rate_mb_s else 0
        self.buffer = bytearray()
        self.fd = None

    def open(self):
        """Opens the file for writing."""
        self.fd = os.open(self.filepath, os.O_WRONLY | os.O_CREAT | os.O_APPEND)
        return self

    def close(self):
        """Flushes remaining data and closes the file."""
        if self.fd is not None:
            try:
                self.flush()
            finally:
                os.close(self.fd)
                self.fd = None

    def __enter__(self):
        return self.open()

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def write(self, data: bytes):
        """
        Appends data to the buffer and flushes in chunks if it reaches chunk_size_bytes.
        """
        if self.fd is None:
            raise ValueError("I/O operation on closed file.")
        
        self.buffer.extend(data)
        
        while len(self.buffer) >= self.chunk_size_bytes:
            chunk = self.buffer[:self.chunk_size_bytes]
            self.buffer = self.buffer[self.chunk_size_bytes:]
            self._flush_chunk(chunk)

    def _flush_chunk(self, chunk: bytes):
        """Writes a chunk to the disk, syncs, and applies rate throttling."""
        start_time = time.time()
        
        written = 0
        chunk_len = len(chunk)
        while written < chunk_len:
            bytes_written = os.write(self.fd, memoryview(chunk)[written:])
            written += bytes_written
        
        # Ensure the chunk is committed to disk
        os.fsync(self.fd)
        
        # Throttling
        elapsed_time = time.time() - start_time
        if self.max_rate_bytes_s > 0:
            expected_time = chunk_len / self.max_rate_bytes_s
            if expected_time > elapsed_time:
                time.sleep(expected_time - elapsed_time)
                
    def flush(self):
        """Flushes any remaining data in the buffer to the disk."""
        if self.fd is None:
            raise ValueError("I/O operation on closed file.")
            
        if self.buffer:
            self._flush_chunk(self.buffer)
            self.buffer = bytearray()
