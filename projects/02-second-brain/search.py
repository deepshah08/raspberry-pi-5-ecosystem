import chromadb
from chromadb.config import Settings

def get_db_client(db_path="./chroma_db"):
    return chromadb.PersistentClient(path=db_path)

def search(query, db_path="./chroma_db", collection_name="second_brain", n_results=5, metadata_filter=None):
    if not query or not query.strip():
        return []
        
    client = get_db_client(db_path)
    try:
        collection = client.get_collection(name=collection_name)
    except Exception as e:
        print(f"Error accessing collection: {e}")
        return []

    # Prepare query arguments
    kwargs = {
        "query_texts": [query],
        "n_results": n_results
    }
    
    if metadata_filter:
        kwargs["where"] = metadata_filter

    results = collection.query(**kwargs)
    
    formatted_results = []
    if results and "documents" in results and results["documents"]:
        docs = results["documents"][0]
        metas = results["metadatas"][0] if "metadatas" in results and results["metadatas"] else [{}] * len(docs)
        ids = results.get("ids", [[]])[0] if results.get("ids") else [""] * len(docs)
        distances = results.get("distances", [[]])[0] if results.get("distances") else [None] * len(docs)
        
        for doc, meta, doc_id, dist in zip(docs, metas, ids, distances):
            formatted_results.append({
                "id": doc_id,
                "distance": dist,
                "document": doc,
                "metadata": meta
            })
            
    return formatted_results

if __name__ == "__main__":
    import sys
    import json
    
    if len(sys.argv) > 1:
        query = sys.argv[1]
        filter_ext = sys.argv[2] if len(sys.argv) > 2 else None
        
        metadata_filter = None
        if filter_ext:
            metadata_filter = {"extension": filter_ext}
            
        results = search(query, metadata_filter=metadata_filter)
        
        print(json.dumps(results, indent=2))
    else:
        print("Usage: python search.py <query> [optional_file_extension_filter]")
