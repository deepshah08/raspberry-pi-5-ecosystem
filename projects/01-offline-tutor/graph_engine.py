import networkx as nx
import os
import json
import logging
from pathlib import Path

GRAPH_DB_PATH = Path(__file__).resolve().parent / "knowledge_graph.gml"

logger = logging.getLogger(__name__)

class GraphEngine:
    def __init__(self):
        self.graph = nx.DiGraph()
        self.load_graph()
        
    def load_graph(self):
        if GRAPH_DB_PATH.exists():
            try:
                self.graph = nx.read_gml(str(GRAPH_DB_PATH))
            except Exception as e:
                logger.error(f"Failed to load graph: {e}")
                
    def save_graph(self):
        nx.write_gml(self.graph, str(GRAPH_DB_PATH))
        
    def add_relationship(self, concept: str, prerequisite: str):
        concept = concept.lower().strip()
        prerequisite = prerequisite.lower().strip()
        self.graph.add_edge(prerequisite, concept)
        self.save_graph()
        
    def get_prerequisites(self, concept: str):
        concept = concept.lower().strip()
        if concept in self.graph:
            return list(self.graph.predecessors(concept))
        return []
        
    def generate_learning_path(self, target_concept: str):
        concept = target_concept.lower().strip()
        if concept not in self.graph:
            return None
        
        ancestors = nx.ancestors(self.graph, concept)
        subgraph = self.graph.subgraph(list(ancestors) + [concept])
        try:
            path = list(nx.topological_sort(subgraph))
            return path
        except nx.NetworkXUnfeasible:
            return list(ancestors) + [concept]

    def get_graph_data(self):
        """Exports the graph data for frontend visualization."""
        nodes = [{"id": node, "label": node.title()} for node in self.graph.nodes()]
        # The edges in graph represent: prerequisite -> concept
        edges = [{"from": u, "to": v} for u, v in self.graph.edges()]
        return {"nodes": nodes, "edges": edges}
