import os
import chromadb
from chromadb.config import Settings
from pypdf import PdfReader
import hashlib

def get_db_client(db_path="./chroma_db"):
    return chromadb.PersistentClient(path=db_path)

def read_pdf(file_path):
    text = ""
    try:
        reader = PdfReader(file_path)
        for page in reader.pages:
            extracted = page.extract_text()
            if extracted:
                text += extracted + "\n"
    except Exception as e:
        print(f"Error reading PDF {file_path}: {e}")
    return text

def read_text(file_path):
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception as e:
        print(f"Error reading {file_path}: {e}")
        return ""

def chunk_text(text, chunk_size=1000, overlap=200):
    chunks = []
    start = 0
    step = max(1, chunk_size - overlap)
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start += step
    return chunks

def ingest_directory(directory_path, db_path="./chroma_db", collection_name="second_brain"):
    client = get_db_client(db_path)
    collection = client.get_or_create_collection(name=collection_name)
    
    supported_extensions = {".md", ".txt", ".pdf"}
    
    documents = []
    metadatas = []
    ids = []
    
    for root, _, files in os.walk(directory_path):
        for file in files:
            ext = os.path.splitext(file)[1].lower()
            if ext not in supported_extensions:
                continue
                
            file_path = os.path.join(root, file)
            
            if ext == ".pdf":
                text = read_pdf(file_path)
            else:
                text = read_text(file_path)
                
            if not text.strip():
                continue
                
            chunks = chunk_text(text)
            
            for i, chunk in enumerate(chunks):
                chunk_id = hashlib.md5(f"{file_path}_{i}".encode()).hexdigest()
                documents.append(chunk)
                metadatas.append({
                    "source": file_path,
                    "extension": ext
                })
                ids.append(chunk_id)
                
    if documents:
        # Add in batches to avoid large payloads if many files
        batch_size = 5000
        for i in range(0, len(documents), batch_size):
            collection.add(
                documents=documents[i:i+batch_size],
                metadatas=metadatas[i:i+batch_size],
                ids=ids[i:i+batch_size]
            )
        return len(documents)
    return 0

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        target_dir = sys.argv[1]
        count = ingest_directory(target_dir)
        print(f"Ingested {count} chunks into ChromaDB.")
    else:
        print("Usage: python ingest.py <directory_to_ingest>")
