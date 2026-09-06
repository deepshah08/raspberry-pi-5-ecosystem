import sys
from pathlib import Path

# Ensure standalone test execution
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import json
from io import StringIO
import pytest
from journal_aggregator import JournalParser, SeverityClassifier, IncidentCorrelator, AlertFormatter, setup_argparse

def test_parser_basic():
    data = '{"PRIORITY": "3", "MESSAGE": "test"}\n{"invalid_json\n{"PRIORITY": "4", "MESSAGE": "test2"}'
    parser = JournalParser(StringIO(data))
    entries = list(parser.parse())
    assert len(entries) == 2
    assert entries[0]["PRIORITY"] == "3"
    assert entries[1]["PRIORITY"] == "4"

def test_severity_filtering():
    classifier = SeverityClassifier(max_priority=3)
    
    # Priority 3 (keep)
    entry1 = classifier.categorize({"PRIORITY": "3", "_SYSTEMD_UNIT": "docker.service"})
    assert entry1 is not None
    assert entry1["_CLASSIFIED_PRIORITY"] == 3
    assert entry1["_CLASSIFIED_SUBSYSTEM"] == "docker.service"
    
    # Priority 4 (discard)
    entry2 = classifier.categorize({"PRIORITY": "4", "SYSLOG_IDENTIFIER": "kernel"})
    assert entry2 is None
    
    # Missing priority
    entry3 = classifier.categorize({"MESSAGE": "test"})
    assert entry3 is None
    
    # Invalid priority
    entry4 = classifier.categorize({"PRIORITY": "invalid", "_TRANSPORT": "journal"})
    assert entry4 is None
    
def test_cascade_error_detection():
    correlator = IncidentCorrelator(threshold=2, window=60)
    
    e1 = correlator.process({"_CLASSIFIED_SUBSYSTEM": "unit1", "__REALTIME_TIMESTAMP": "10000000"})
    assert e1["_IS_CASCADE"] is False
    
    e2 = correlator.process({"_CLASSIFIED_SUBSYSTEM": "unit1", "__REALTIME_TIMESTAMP": "20000000"})
    assert e2["_IS_CASCADE"] is False
    
    e3 = correlator.process({"_CLASSIFIED_SUBSYSTEM": "unit1", "__REALTIME_TIMESTAMP": "30000000"})
    assert e3["_IS_CASCADE"] is True
    
    e4 = correlator.process({"_CLASSIFIED_SUBSYSTEM": "unit1", "__REALTIME_TIMESTAMP": "40000000"})
    assert e4["_IS_CASCADE"] is False

def test_alert_formatter():
    formatter = AlertFormatter()
    
    msg1 = formatter.format({
        "_IS_CASCADE": False,
        "_CLASSIFIED_PRIORITY": 3,
        "_CLASSIFIED_SUBSYSTEM": "docker.service",
        "MESSAGE": "Crash loop"
    })
    assert msg1 == "ALERT: [3] docker.service: Crash loop"
    
    msg2 = formatter.format({
        "_IS_CASCADE": True,
        "_CLASSIFIED_PRIORITY": 2,
        "_CLASSIFIED_SUBSYSTEM": "kernel",
        "MESSAGE": "OOM"
    })
    assert msg2 == "ALERT [CASCADE FAILURE]: [2] kernel: OOM"

def test_cli_arguments():
    parser = setup_argparse()
    args = parser.parse_args(["--input-file", "test.json", "--priority", "2", "--dry-run", "--json"])
    assert args.input_file == "test.json"
    assert args.priority == 2
    assert args.dry_run is True
    assert args.json is True
