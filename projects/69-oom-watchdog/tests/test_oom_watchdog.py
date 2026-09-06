import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from unittest.mock import MagicMock
import time
import json
from oom_watchdog import ContainerMemorySampler, LeakSlopeCalculator, PolicyEvaluator, AlertFormatter, parse_args

@pytest.fixture
def mock_docker_client():
    client = MagicMock()
    return client

def test_sampler_basic(mock_docker_client):
    c1 = MagicMock()
    c1.name = "test_container"
    c1.stats.return_value = {
        'memory_stats': {
            'usage': 2000,
            'limit': 5000,
            'stats': {'cache': 500}
        }
    }
    mock_docker_client.containers.list.return_value = [c1]
    
    sampler = ContainerMemorySampler(mock_docker_client)
    stats = sampler.get_stats()
    
    assert "test_container" in stats
    assert stats["test_container"]["usage_bytes"] == 1500
    assert stats["test_container"]["limit_bytes"] == 5000

def test_leak_slope_calculator():
    calc = LeakSlopeCalculator()
    
    # Needs at least 2 points
    assert calc.calculate_slope("test") is None
    
    calc.add_sample("test", 100 * 1024 * 1024, 1000, 10.0) # 100MB
    calc.add_sample("test", 150 * 1024 * 1024, 1000, 70.0) # 150MB, 1 min later
    
    slope = calc.calculate_slope("test")
    # (150 - 100) / 1 min = 50 MB/min
    assert slope == 50.0

def test_policy_evaluator_protected():
    evaluator = PolicyEvaluator()
    # Should ignore protected containers even with high usage
    alert = evaluator.evaluate("pihole", 900, 1000, 100.0)
    assert alert is None

def test_policy_evaluator_high_usage():
    evaluator = PolicyEvaluator(threshold_percent=85.0)
    alert = evaluator.evaluate("app1", 860, 1000, 0.0)
    assert alert is not None
    assert alert["reason"] == "high_usage"

def test_policy_evaluator_fast_leak():
    evaluator = PolicyEvaluator()
    limit = 1000 * 1024 * 1024
    usage = 100 * 1024 * 1024
    
    # slope = 100 MB/min. Remaining: 900 MB. ETA = 9 mins
    alert = evaluator.evaluate("app2", usage, limit, 100.0)
    assert alert is not None
    assert alert["reason"] == "fast_leak"
    assert alert["eta_minutes"] == 9.0

def test_alert_formatter():
    alert_data = {
        "container_name": "test_app",
        "usage_percent": 90.0,
        "slope_mb_min": 10.5,
        "eta_minutes": 5.0,
        "reason": "fast_leak"
    }
    
    json_out = AlertFormatter.format_alert(alert_data, True)
    parsed = json.loads(json_out)
    assert parsed["container_name"] == "test_app"
    
    str_out = AlertFormatter.format_alert(alert_data, False)
    assert "test_app" in str_out
    assert "90.00%" in str_out
    assert "10.50 MB/min" in str_out
    assert "5.00 minutes" in str_out

def test_cli_args_parsing():
    # Simulating parse_args manually since argparse uses sys.argv
    import sys
    sys.argv = ["oom_watchdog.py", "--check-now", "--interval", "120", "--json", "--dry-run"]
    args = parse_args()
    assert args.check_now is True
    assert args.interval == 120
    assert args.json is True
    assert args.dry_run is True

