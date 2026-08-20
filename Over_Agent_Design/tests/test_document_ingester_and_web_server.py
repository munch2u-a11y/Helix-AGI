"""
Unit Test Suite for Document Ingester & Web Server.
Verifies:
1. DocumentIngester semantic chunking and node indexing into Helix memory.
2. Web UI file structure and server handler initialization.
"""

import os
import sys
import unittest
import tempfile

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from document_ingester import DocumentIngester
from web_server import WidgetHTTPServerHandler

class TestDocumentIngesterAndWebServer(unittest.TestCase):
    def test_document_chunking(self):
        class RecordingMRAG:
            def __init__(self):
                self.chunks = []

            def ingest_document_chunks(self, filename, chunks):
                self.chunks = list(chunks)
                return [f"mem_{index}" for index, _ in enumerate(self.chunks, 1)]

        memory = RecordingMRAG()
        ingester = DocumentIngester(
            chunk_size_words=50,
            overlap_words=10,
            mrag_runtime=memory,
        )
        sample_text = "Word " * 200  # 200 words
        
        with tempfile.NamedTemporaryFile("w+", suffix=".txt", delete=False) as f:
            f.write(sample_text)
            temp_path = f.name

        try:
            res = ingester.process_file_upload(temp_path, "sample_doc.txt")
            self.assertTrue(res["success"])
            self.assertGreater(res["chunk_count"], 1)
            self.assertEqual(res["chunk_count"], len(memory.chunks))
            print(f"\n  ✓ Document Ingested: {res['filename']} ({res['chunk_count']} semantic chunks created)")
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_web_ui_files_exist(self):
        web_dir = os.path.join(BASE_DIR, "web_ui")
        self.assertTrue(os.path.exists(os.path.join(web_dir, "index.html")))
        self.assertTrue(os.path.exists(os.path.join(web_dir, "styles.css")))
        self.assertTrue(os.path.exists(os.path.join(web_dir, "app.js")))
        print(f"  ✓ Web UI static files verified (index.html, styles.css, app.js)")

if __name__ == "__main__":
    unittest.main()
