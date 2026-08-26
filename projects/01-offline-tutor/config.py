import os
from pathlib import Path

INTERNAL_STORAGE = Path(os.getenv('INTERNAL_STORAGE', '~/.offline_tutor')).expanduser()
INTERNAL_STORAGE.mkdir(parents=True, exist_ok=True)

CHROMADB_DIR = INTERNAL_STORAGE / 'chroma_db'
GRAPH_DB_PATH = INTERNAL_STORAGE / 'knowledge_graph.gml'
CACHE_DB_PATH = INTERNAL_STORAGE / 'semantic_cache.sqlite3'

EMBEDDING_MODEL = 'all-MiniLM-L6-v2'
LLM_MODEL = 'phi3:mini'
LLM_URL = 'http://localhost:11434'
