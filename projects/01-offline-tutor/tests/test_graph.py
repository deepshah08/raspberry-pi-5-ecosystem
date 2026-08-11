import json
import unittest
from graph_engine import GraphEngine

class TestGraphEngine(unittest.TestCase):
    def test_get_graph_data(self):
        engine = GraphEngine()
        
        # Adding mock data
        engine.add_relationship("Neural Networks", "Linear Algebra")
        engine.add_relationship("Neural Networks", "Calculus")
        engine.add_relationship("Deep Learning", "Neural Networks")
        
        # Retrieve graph data
        data = engine.get_graph_data()
        
        self.assertIn('nodes', data)
        self.assertIn('edges', data)
        self.assertGreater(len(data['nodes']), 0)
        self.assertGreater(len(data['edges']), 0)

if __name__ == "__main__":
    unittest.main()
