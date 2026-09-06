import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
import responses
from crawler_sentry import Crawler

@responses.activate
def test_crawler_html_link_extraction():
    base_url = "http://testserver"

    html_content = """
    <html>
        <head>
            <link rel="stylesheet" href="/style.css">
        </head>
        <body>
            <a href="/page2">Page 2</a>
            <img src="/image.png">
            <script src="/script.js"></script>
        </body>
    </html>
    """

    responses.add(responses.GET, base_url, body=html_content, status=200, content_type="text/html")
    responses.add(responses.GET, f"{base_url}/page2", body="ok", status=200, content_type="text/html")
    responses.add(responses.HEAD, f"{base_url}/style.css", status=200)
    responses.add(responses.HEAD, f"{base_url}/image.png", status=200)
    responses.add(responses.HEAD, f"{base_url}/script.js", status=200)

    crawler = Crawler(base_urls=[base_url], depth=2, max_concurrency=3, dry_run=True)
    report = crawler.run()

    assert report["total_scanned"] == 5
    assert len(report["errors"]) == 0
    urls = [r["url"] for r in report["results"]]
    assert base_url in urls
    assert f"{base_url}/page2" in urls
    assert f"{base_url}/style.css" in urls
    assert f"{base_url}/image.png" in urls
    assert f"{base_url}/script.js" in urls

@responses.activate
def test_crawler_4xx_5xx_detection():
    base_url = "http://testserver"

    responses.add(responses.GET, base_url, status=500)

    crawler = Crawler(base_urls=[base_url], depth=2, max_concurrency=3, dry_run=True)
    report = crawler.run()

    assert report["total_scanned"] == 1
    assert len(report["errors"]) == 1
    assert report["errors"][0]["status_code"] == 500
    assert report["errors"][0]["error"] == "HTTP 500"

@responses.activate
def test_crawler_slow_response(monkeypatch):
    import time
    base_url = "http://testserver"

    responses.add(responses.GET, base_url, body="ok", status=200)

    crawler = Crawler(base_urls=[base_url], depth=2, max_concurrency=3, dry_run=True)

    original_time = time.time
    def mock_time():
        if not hasattr(mock_time, "call_count"):
            mock_time.call_count = 0
        mock_time.call_count += 1
        return original_time() if mock_time.call_count == 1 else original_time() + 1.5

    monkeypatch.setattr(time, "time", mock_time)

    report = crawler.run()

    assert report["total_scanned"] == 1
    assert len(report["errors"]) == 1
    assert report["errors"][0]["slow"] == True

@responses.activate
def test_crawler_depth_limit():
    base_url = "http://testserver"

    html_page1 = '<a href="/page2">Page 2</a>'
    html_page2 = '<a href="/page3">Page 3</a>'

    responses.add(responses.GET, base_url, body=html_page1, status=200, content_type="text/html")
    responses.add(responses.GET, f"{base_url}/page2", body=html_page2, status=200, content_type="text/html")
    responses.add(responses.GET, f"{base_url}/page3", body="ok", status=200, content_type="text/html")

    crawler = Crawler(base_urls=[base_url], depth=1, max_concurrency=3, dry_run=True)
    report = crawler.run()

    urls = [r["url"] for r in report["results"]]
    assert base_url in urls
    assert f"{base_url}/page2" in urls
    assert f"{base_url}/page3" not in urls

def test_cli_parsing(monkeypatch, capsys):
    from crawler_sentry import main
    monkeypatch.setattr(sys, 'argv', ['crawler_sentry.py', '--crawl-now', '--base-urls', 'http://testserver', '--dry-run', '--json'])

    # Mock crawler run
    original_run = Crawler.run
    def mock_run(self):
        return {"total_scanned": 1, "errors": [], "results": []}

    monkeypatch.setattr(Crawler, "run", mock_run)
    main()

    captured = capsys.readouterr()
    import json
    output = json.loads(captured.out)
    assert output["total_scanned"] == 1
