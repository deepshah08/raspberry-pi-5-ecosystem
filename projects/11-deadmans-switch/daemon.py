import os
import time
import logging
import random
import json

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Mersenne prime M521 (2^521 - 1)
_PRIME = 2**521 - 1

def _eval_poly(poly, x, prime):
    accum = 0
    for coeff in reversed(poly):
        accum = (accum * x + coeff) % prime
    return accum

def split_secret(secret_int: int, threshold: int, total_shares: int, prime=_PRIME):
    if threshold > total_shares:
        raise ValueError("Threshold cannot exceed total shares")
    poly = [secret_int] + [random.randint(1, prime - 1) for _ in range(threshold - 1)]
    shares = []
    for x in range(1, total_shares + 1):
        shares.append((x, _eval_poly(poly, x, prime)))
    return shares

def recover_secret(shares: list, prime=_PRIME) -> int:
    x_s, y_s = zip(*shares)
    secret = 0
    k = len(shares)
    for i in range(k):
        num = 1
        den = 1
        for j in range(k):
            if i == j:
                continue
            num = (num * (-x_s[j])) % prime
            den = (den * (x_s[i] - x_s[j])) % prime
        lagrange_coeff = (num * pow(den, prime - 2, prime)) % prime
        secret = (secret + y_s[i] * lagrange_coeff) % prime
    return secret % prime

class DeadMansSwitch:
    def __init__(self, ping_file="ping.txt", timeout_seconds=30*86400):
        self.ping_file = ping_file
        self.timeout_seconds = timeout_seconds

    def touch_ping(self):
        with open(self.ping_file, 'w') as f:
            f.write(str(time.time()))

    def check_alive(self) -> bool:
        if not os.path.exists(self.ping_file):
            self.touch_ping()
            return True
        mtime = os.path.getmtime(self.ping_file)
        return (time.time() - mtime) <= self.timeout_seconds

    def trigger(self, secret: str = "VAULT_BACKUP_EMERGENCY_KEY_2026", threshold: int = 3, total: int = 5):
        logger.warning("Triggering Dead Man's Switch contingency protocol!")
        secret_int = int.from_bytes(secret.encode('utf-8'), 'big')
        shares = split_secret(secret_int, threshold, total)
        return [f"{x}-{y:x}" for x, y in shares]
