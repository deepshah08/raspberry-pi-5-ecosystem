import time
import logging
from typing import List, Dict, Any, Optional
from qdrant_client import QdrantClient
from qdrant_client.http.models import Distance, VectorParams, PointStruct, UpdateStatus, Filter, FieldCondition, MatchValue
from qdrant_client.http.exceptions import UnexpectedResponse

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class OmniSearchClient:
    def __init__(self, host: str = "localhost", port: int = 6333, grpc_port: int = 6334, memory: bool = False, max_retries: int = 3, retry_delay: float = 1.0):
        self.host = host
        self.port = port
        self.grpc_port = grpc_port
        self.memory = memory
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.client = self._connect()

    def _connect(self) -> QdrantClient:
        if self.memory:
            return QdrantClient(":memory:")

        retries = 0
        while retries < self.max_retries:
            try:
                client = QdrantClient(host=self.host, port=self.port, grpc_port=self.grpc_port)
                # Verify connection by attempting to list collections
                client.get_collections()
                return client
            except Exception as e:
                retries += 1
                logger.warning(f"Connection to Qdrant failed (Attempt {retries}/{self.max_retries}): {e}")
                if retries < self.max_retries:
                    time.sleep(self.retry_delay * (2 ** (retries - 1)))  # Exponential backoff

        raise ConnectionError(f"Failed to connect to Qdrant after {self.max_retries} attempts.")

    def init_collection(self, collection_name: str = "media_frames", vector_size: int = 512, distance: Distance = Distance.COSINE):
        """
        Initializes the collection for storing media frame vectors.
        vector_size: 512 for MobileCLIP, 768 for SigLIP.
        """
        try:
            collections_response = self.client.get_collections()
            collection_names = [collection.name for collection in collections_response.collections]

            if collection_name in collection_names:
                logger.info(f"Collection '{collection_name}' already exists.")
                # We could check if existing dimension matches
                return

            self.client.create_collection(
                collection_name=collection_name,
                vectors_config=VectorParams(size=vector_size, distance=distance)
            )
            logger.info(f"Collection '{collection_name}' created successfully with dimension {vector_size}.")
        except Exception as e:
            logger.error(f"Error initializing collection: {e}")
            raise

    def batch_upsert(self, collection_name: str, points: List[Dict[str, Any]]):
        """
        Upserts a batch of points into the specified collection.
        Expected format for points:
        [
            {
                "id": 1,
                "vector": [0.1, 0.2, ...],
                "payload": {
                    "file_path": "/path/to/image.jpg",
                    "timestamp_sec": 123.45,
                    "item_type": "photo",
                    "title": "A photo of a dog",
                    "tags": ["dog", "pet", "animal"]
                }
            },
            ...
        ]
        """
        if not points:
            return

        point_structs = []
        for point in points:
            # Basic validation
            payload = point.get("payload", {})
            required_payload_keys = ["file_path", "timestamp_sec", "item_type", "title", "tags"]
            for key in required_payload_keys:
                if key not in payload:
                    raise ValueError(f"Missing required payload key: {key}")

            point_structs.append(
                PointStruct(
                    id=point["id"],
                    vector=point["vector"],
                    payload=payload
                )
            )

        operation_info = self.client.upsert(
            collection_name=collection_name,
            wait=True,
            points=point_structs
        )

        if operation_info.status != UpdateStatus.COMPLETED:
            logger.warning(f"Upsert operation did not complete successfully. Status: {operation_info.status}")

        return operation_info

    def search(self, collection_name: str, query_vector: List[float], top_k: int = 10, threshold: float = 0.5, filter_dict: Optional[Dict[str, Any]] = None):
        """
        Searches the collection for the closest vectors to the query vector.
        """
        query_filter = None
        if filter_dict:
            must_conditions = []
            for key, value in filter_dict.items():
                must_conditions.append(
                    FieldCondition(
                        key=key,
                        match=MatchValue(value=value)
                    )
                )
            query_filter = Filter(must=must_conditions)

        search_result = self.client.query_points(
            collection_name=collection_name,
            query=query_vector,
            limit=top_k,
            score_threshold=threshold,
            query_filter=query_filter
        ).points

        return search_result
