import unittest
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from graph_engine import GraphEngine
from agent import SocraticAgent
from concept_extractor import ConceptExtractor

class TestOfflineTutor(unittest.TestCase):
    def setUp(self):
        self.engine = GraphEngine()
        self.agent = SocraticAgent()
        self.extractor = ConceptExtractor()
        
    def test_prerequisites_and_learning_path(self):
        self.engine.add_relationship('Machine Learning', 'Linear Algebra')
        self.engine.add_relationship('Machine Learning', 'Probability')
        self.engine.add_relationship('Deep Learning', 'Machine Learning')
        
        prereqs = self.engine.get_prerequisites('Machine Learning')
        self.assertIn('linear algebra', prereqs)
        self.assertIn('probability', prereqs)
        
        path = self.engine.generate_learning_path('Deep Learning')
        self.assertIsNotNone(path)
        self.assertEqual(path[-1], 'deep learning')
        
    def test_concept_extractor_fallback(self):
        text = 'Before learning Neural Networks, you must understand Calculus.'
        pairs = self.extractor.extract_relationships(text)
        self.assertGreater(len(pairs), 0)
        
    def test_socratic_agent_fallback_response(self):
        res = self.agent.generate_response('Backpropagation', 'Calculus chain rule applied to neural networks')
        self.assertIsInstance(res, str)
        self.assertGreater(len(res), 5)

if __name__ == '__main__':
    unittest.main()
