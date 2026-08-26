import logging
import re
from config import LLM_MODEL, LLM_URL

logger = logging.getLogger(__name__)

class ConceptExtractor:
    def __init__(self):
        try:
            import ollama
            self.client = ollama.Client(host=LLM_URL)
        except Exception:
            self.client = None
        
    def extract_relationships(self, text: str) -> list:
        """
        Extracts [Concept] -> [Prerequisite] pairs from text.
        """
        if not text:
            return []
            
        if self.client:
            sys_prompt = """
            You are a knowledge graph extractor. 
            Extract key educational concepts and their prerequisites from the provided text.
            Output ONLY a list of pairs in this exact format:
            [Concept] -> [Prerequisite]
            """
            try:
                response = self.client.chat(model=LLM_MODEL, messages=[
                    {'role': 'system', 'content': sys_prompt},
                    {'role': 'user', 'content': text}
                ])
                content = response['message']['content']
                pairs = []
                for line in content.split('\n'):
                    line = line.strip()
                    if '->' in line:
                        parts = line.split('->')
                        if len(parts) == 2:
                            c = parts[0].strip(' []')
                            p = parts[1].strip(' []')
                            if c and p:
                                pairs.append((c, p))
                if pairs:
                    return pairs
            except Exception as e:
                logger.error(f"LLM extraction error: {e}")
                
        # Rule-based fallback extraction
        pairs = []
        patterns = [
            r'before (?:you |learning )?([a-zA-Z\s]+),? you (?:must|need to) (?:understand|know|learn) ([a-zA-Z\s]+)',
            r'([a-zA-Z\s]+) requires (?:prior knowledge of )?([a-zA-Z\s]+)',
            r'([a-zA-Z\s]+) is a prerequisite for ([a-zA-Z\s]+)'
        ]
        for pattern in patterns:
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for m in matches:
                g1, g2 = m.group(1).strip(), m.group(2).strip()
                if 'prerequisite for' in pattern:
                    pairs.append((g2, g1))
                else:
                    pairs.append((g1, g2))
        return pairs
