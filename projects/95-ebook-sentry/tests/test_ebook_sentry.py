import sys
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ebook_sentry import LibraryAuditor, OPDSValidator, parse_args

# Mock Data
MOCK_LIBRARIES_RESPONSE = {
    "libraries": [
        {"id": "lib1", "name": "Audiobooks"},
        {"id": "lib2", "name": "Podcasts"}
    ]
}

MOCK_ITEMS_RESPONSE = {
    "results": [
        {
            "id": "item1",
            "media": {
                "coverPath": "/covers/item1.jpg",
                "hasCover": True,
                "metadata": {
                    "title": "Good Book",
                    "authors": ["Author One"],
                    "isbn": "1234567890"
                }
            }
        },
        {
            "id": "item2",
            "media": {
                "coverPath": None,
                "hasCover": False,
                "metadata": {
                    "title": "Bad Book",
                    "authors": [],
                    "authorName": "",
                    "isbn": None
                }
            }
        }
    ]
}

MOCK_OPDS_XML_VALID = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Calibre Library</title>
</feed>
"""

MOCK_OPDS_XML_INVALID = """<?xml version="1.0" encoding="utf-8"?>
<not_a_feed xmlns="http://www.w3.org/2005/Atom">
  <title>Invalid</title>
</not_a_feed>
"""

MOCK_OPDS_XML_MALFORMED = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Calibre Library</title>
"""

@patch('requests.get')
def test_audiobookshelf_missing_metadata(mock_get):
    # Setup mock returns based on URL
    def mock_get_side_effect(url):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        if url.endswith("/api/libraries"):
            mock_resp.json.return_value = MOCK_LIBRARIES_RESPONSE
        elif url.endswith("/items"):
            mock_resp.json.return_value = MOCK_ITEMS_RESPONSE
        else:
            mock_resp.json.return_value = {}
        return mock_resp

    mock_get.side_effect = mock_get_side_effect

    auditor = LibraryAuditor(abs_url="http://mock-abs", dry_run=True)
    issues = auditor.audit_audiobookshelf()

    assert len(issues) == 2
    issue = issues[0]
    assert issue["item_id"] == "item2"
    assert "cover" in issue["missing_fields"]
    assert "author" in issue["missing_fields"]
    assert "isbn" in issue["missing_fields"]

def test_cli_args_parsing():
    test_args = ["ebook_sentry.py", "--audit-now", "--abs-url", "http://abs", "--calibre-url", "http://calibre", "--dry-run", "--json"]
    with patch.object(sys, 'argv', test_args):
        args = parse_args()
        assert args.audit_now is True
        assert args.abs_url == "http://abs"
        assert args.calibre_url == "http://calibre"
        assert args.dry_run is True
        assert args.json is True


@patch('requests.get')
def test_opds_xml_valid(mock_get):
    mock_resp = MagicMock()
    mock_resp.text = MOCK_OPDS_XML_VALID
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    validator = OPDSValidator(calibre_url="http://mock-calibre")
    issues = validator.validate_feed()

    assert len(issues) == 0

@patch('requests.get')
def test_opds_xml_invalid_root(mock_get):
    mock_resp = MagicMock()
    mock_resp.text = MOCK_OPDS_XML_INVALID
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    validator = OPDSValidator(calibre_url="http://mock-calibre")
    issues = validator.validate_feed()

    assert len(issues) == 1
    assert issues[0]["type"] == "opds_validation_error"
    assert "Root element is not 'feed'" in issues[0]["message"]

@patch('requests.get')
def test_opds_xml_malformed(mock_get):
    mock_resp = MagicMock()
    mock_resp.text = MOCK_OPDS_XML_MALFORMED
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    validator = OPDSValidator(calibre_url="http://mock-calibre")
    issues = validator.validate_feed()

    assert len(issues) == 1
    assert issues[0]["type"] == "opds_validation_error"
    assert "XML parsing failed" in issues[0]["message"]

def test_dry_run_safety():
    # Test that setting dry_run to True sets it properly in LibraryAuditor
    auditor = LibraryAuditor(abs_url="http://mock-abs", dry_run=True)
    assert auditor.dry_run is True
    # The actual functionality doesn't write anything currently, so safety is guaranteed by lack of write methods,
    # but we assert the flag is kept.
