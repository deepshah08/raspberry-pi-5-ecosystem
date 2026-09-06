# Homelab Document OCR Classifier & Ingest Bridge

Automated document OCR classification, metadata tagging, and ingest pipeline connecting scanned documents to homelab document archives. Automatically detects file types, runs lightweight OCR/regex parsing for document categories (Tax, Medical, Utilities, Invoices), and routes documents to structured monthly archive directories.

## Architecture

```mermaid
graph TD
    A[Scanned Document / PDF] --> B(Ingest Watcher)
    B --> C{Content Classifier}
    C -- Matches "w2", "1099" --> D[Tax]
    C -- Matches "medical", "copay" --> E[Medical]
    C -- Matches "electric", "bill" --> F[Utilities]
    C -- Matches "invoice", "receipt" --> G[Invoices]
    C -- No Match --> H[Uncategorized]
    D --> I(Archival Router)
    E --> I
    F --> I
    G --> I
    H --> I
    I --> J[archive/YYYY/Category/]
```

## Runbook

### Setup

```bash
docker-compose up -d --build
```

### CLI Usage

You can also run the script manually:

```bash
python document_classifier.py --input-dir ./input --scan-now
```

- `--input-dir <path>`: Required. Directory to watch for documents.
- `--scan-now`: Run once and exit.
- `--dry-run`: Do not move files. Log what would happen.
- `--json`: Output logs in JSON format.

### Metrics

Prometheus metrics are exposed on port 9130:
- `homelab_docs_classified_total`
- `homelab_docs_failed_total`
