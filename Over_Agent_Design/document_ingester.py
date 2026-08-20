"""
Document Ingestion & Semantic Chunking Engine — Subconscious Over-Agent System.

Parses drag-and-dropped files (.txt, .md, .py, .json, .pdf, images),
splits text into 500-token semantic chunks with 50-token overlapping boundaries,
and indexes memory nodes into /home/nemo/Helix/data/memory and mrag_adapter.py.
"""

import os
import sys
import json
import time
import glob
from typing import Dict, List, Any

HELIX_MEMORY_PATH = "/home/nemo/Helix/data/memory"
os.makedirs(HELIX_MEMORY_PATH, exist_ok=True)

class DocumentIngester:
    def __init__(self, chunk_size_words: int = 400, overlap_words: int = 40):
        self.chunk_size_words = chunk_size_words
        self.overlap_words = overlap_words

    def process_file_upload(self, file_path: str, filename: str) -> Dict[str, Any]:
        """
        Parses an uploaded file, extracts text, chunks it semantically, and persists to memory store.
        """
        ext = os.path.splitext(filename)[1].lower()
        content_text = ""
        
        try:
            if ext in [".txt", ".md", ".py", ".json", ".csv", ".sh", ".js", ".html", ".css"]:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    content_text = f.read()
            elif ext == ".pdf":
                content_text = self._extract_pdf_text(file_path)
            elif ext in [".png", ".jpg", ".jpeg", ".gif", ".webp"]:
                content_text = f"[Image File Node: {filename} ({os.path.getsize(file_path)} bytes). Desktop vision screenshot or media asset dropped into memory.]"
            else:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    content_text = f.read(5000)
        except Exception as e:
            return {"success": False, "error": f"Could not parse file '{filename}': {e}"}

        if not content_text.strip():
            return {"success": False, "error": f"File '{filename}' contained no readable text."}

        # Create 500-token (400-word) semantic chunks with 40-word overlap
        chunks = self._chunk_text_semantically(content_text, filename)
        
        # Persist memory chunks to Helix memory store
        saved_nodes = self._persist_chunks_to_memory(filename, chunks)
        
        return {
            "success": True,
            "filename": filename,
            "total_chars": len(content_text),
            "chunk_count": len(chunks),
            "saved_nodes": saved_nodes
        }

    def _chunk_text_semantically(self, text: str, source_name: str) -> List[Dict[str, Any]]:
        words = text.split()
        if not words:
            return []

        chunks = []
        step = self.chunk_size_words - self.overlap_words
        if step <= 0:
            step = self.chunk_size_words

        for i in range(0, len(words), step):
            chunk_words = words[i:i + self.chunk_size_words]
            chunk_text = " ".join(chunk_words)
            chunk_index = (i // step) + 1
            
            chunks.append({
                "source": source_name,
                "chunk_index": chunk_index,
                "word_count": len(chunk_words),
                "text": chunk_text
            })
            
        return chunks

    def _persist_chunks_to_memory(self, filename: str, chunks: List[Dict[str, Any]]) -> List[str]:
        saved_paths = []
        clean_name = "".join(c if c.isalnum() else "_" for c in filename)
        timestamp = int(time.time())
        
        for idx, chunk in enumerate(chunks):
            node_filename = f"ingested_{clean_name}_c{idx+1}_{timestamp}.json"
            target_path = os.path.join(HELIX_MEMORY_PATH, node_filename)
            
            data = {
                "id": f"chunk_{clean_name}_{idx+1}",
                "source_file": filename,
                "chunk_index": chunk["chunk_index"],
                "total_chunks": len(chunks),
                "timestamp": timestamp,
                "content": chunk["text"]
            }
            
            try:
                with open(target_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
                saved_paths.append(target_path)
            except Exception:
                pass
                
        return saved_paths

    def _extract_pdf_text(self, file_path: str) -> str:
        # Fallback pdf reader using basic text scanning if pypdf is unavailable
        try:
            import pypdf
            reader = pypdf.PdfReader(file_path)
            text = []
            for page in reader.pages:
                text.append(page.extract_text() or "")
            return "\n".join(text)
        except ImportError:
            with open(file_path, "rb") as f:
                raw = f.read()
                # Basic string extract fallback
                import re
                strings = re.findall(rb"[a-zA-Z0-9\s\.\,\;\:\-\_\(\)\[\]\{\}\'\"\/]{4,}", raw)
                return "\n".join(s.decode("utf-8", errors="ignore") for s in strings[:1000])
