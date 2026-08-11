from typing import List, Dict, Any, Optional

def index_segments(
    collection: Any,
    segments: List[Dict[str, Any]],
    id_prefix: Optional[str] = None
) -> None:
    """
    Indexes a list of transcription segments into a ChromaDB collection.
    
    Args:
        collection (chromadb.api.models.Collection.Collection): The ChromaDB collection.
        segments (List[Dict[str, Any]]): A list of segments containing 'start', 'end', and 'text'.
        id_prefix (Optional[str]): Optional prefix for segment IDs and metadata audio_id to prevent collision.
    """
    if not segments:
        return
        
    ids = []
    documents = []
    metadatas = []
    
    prefix = f"{id_prefix}_" if id_prefix else ""
    for i, segment in enumerate(segments):
        ids.append(f"{prefix}segment_{i}")
        documents.append(segment["text"])
        meta = {
            "start": segment["start"],
            "end": segment["end"]
        }
        if id_prefix:
            meta["audio_id"] = id_prefix
        metadatas.append(meta)
        
    collection.add(
        ids=ids,
        documents=documents,
        metadatas=metadatas
    )

def query_segments(
    collection: Any,
    query: str,
    start_time: Optional[float] = None,
    end_time: Optional[float] = None,
    n_results: int = 5
) -> Dict[str, Any]:
    """
    Queries the ChromaDB collection for segments matching the text query,
    optionally filtering by time range.
    
    Args:
        collection (chromadb.api.models.Collection.Collection): The ChromaDB collection.
        query (str): The search query.
        start_time (Optional[float]): Minimum start time for the segments.
        end_time (Optional[float]): Maximum end time for the segments.
        n_results (int): Number of results to return.
        
    Returns:
        Dict[str, Any]: The query results from ChromaDB.
    """
    where_filter = {}
    
    if start_time is not None or end_time is not None:
        where_filter = {"$and": []}
        
        if start_time is not None:
            where_filter["$and"].append({"start": {"$gte": start_time}})
            
        if end_time is not None:
            where_filter["$and"].append({"end": {"$lte": end_time}})
            
        # Simplify filter if only one condition exists
        if len(where_filter["$and"]) == 1:
            where_filter = where_filter["$and"][0]
        elif len(where_filter["$and"]) == 0:
            where_filter = {}

    kwargs = {
        "query_texts": [query],
        "n_results": n_results
    }
    
    if where_filter:
        kwargs["where"] = where_filter
        
    results = collection.query(**kwargs)
    return results
