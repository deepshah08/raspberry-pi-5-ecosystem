import unittest
import tempfile
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from voice_clone import synthesize_text

class TestVoiceClone(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.TemporaryDirectory()
        self.text_file = os.path.join(self.test_dir.name, 'sample.txt')
        self.output_file = os.path.join(self.test_dir.name, 'output.wav')
        with open(self.text_file, 'w') as f:
            f.write('Hello world, this is a test of the local TTS voice cloning pipeline.')

    def tearDown(self):
        self.test_dir.cleanup()

    def test_synthesize_text(self):
        res = synthesize_text(self.text_file, self.output_file)
        self.assertTrue(res)
        self.assertTrue(os.path.exists(self.output_file))
        self.assertGreater(os.path.getsize(self.output_file), 0)

    def test_missing_file_handling(self):
        res = synthesize_text('nonexistent_text.txt', self.output_file)
        self.assertFalse(res)

if __name__ == '__main__':
    unittest.main()
