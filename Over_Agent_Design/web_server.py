"""
Web Server & SSE Bridge — Subconscious Over-Agent System.

Hosts the Desktop Floating Widget UI (web_ui/), handles drag-and-drop file ingestion,
provides Web-to-Python window drag position bridge (/api/drag_move),
and streams real-time background pulse thoughts & affect updates over SSE.
"""

import os
import sys
import json
import time
import cgi
from http.server import HTTPServer, SimpleHTTPRequestHandler
from typing import Optional, List, Dict, Any

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from subconscious_conductor import SubconsciousConductor
from document_ingester import DocumentIngester
from proactive_vision_agent import ProactiveVisionAgent

WEB_UI_DIR = os.path.join(BASE_DIR, "web_ui")

# Global window reference for native desktop dragging
DESKTOP_WINDOW_REF = None

class WidgetHTTPServerHandler(SimpleHTTPRequestHandler):
    conductor: Optional[SubconsciousConductor] = None
    ingester = DocumentIngester()
    proactive_agent = ProactiveVisionAgent()

    # Drag tracking state
    drag_start_win_x = 0
    drag_start_win_y = 0
    drag_start_screen_x = 0
    drag_start_screen_y = 0

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=WEB_UI_DIR, **kwargs)

    def do_GET(self):
        if self.path == "/api/stream":
            self._handle_sse_stream()
        else:
            super().do_GET()

    def do_POST(self):
        if self.path == "/api/chat":
            self._handle_api_chat()
        elif self.path == "/api/ingest":
            self._handle_api_ingest()
        elif self.path == "/api/drag_start":
            self._handle_drag_start()
        elif self.path == "/api/drag_move":
            self._handle_drag_move()
        else:
            self._send_json_response({"error": "Endpoint not found"}, status=404)

    def _handle_drag_start(self):
        content_length = int(self.headers.get("Content-Length", 0))
        data = json.loads(self.rfile.read(content_length).decode("utf-8"))
        
        WidgetHTTPServerHandler.drag_start_screen_x = data.get("screenX", 0)
        WidgetHTTPServerHandler.drag_start_screen_y = data.get("screenY", 0)
        
        if DESKTOP_WINDOW_REF:
            pos = DESKTOP_WINDOW_REF.pos()
            WidgetHTTPServerHandler.drag_start_win_x = pos.x()
            WidgetHTTPServerHandler.drag_start_win_y = pos.y()

        self._send_json_response({"status": "ok"})

    def _handle_drag_move(self):
        content_length = int(self.headers.get("Content-Length", 0))
        data = json.loads(self.rfile.read(content_length).decode("utf-8"))
        
        curr_screen_x = data.get("screenX", 0)
        curr_screen_y = data.get("screenY", 0)
        
        delta_x = curr_screen_x - WidgetHTTPServerHandler.drag_start_screen_x
        delta_y = curr_screen_y - WidgetHTTPServerHandler.drag_start_screen_y
        
        new_x = WidgetHTTPServerHandler.drag_start_win_x + delta_x
        new_y = WidgetHTTPServerHandler.drag_start_win_y + delta_y
        
        if DESKTOP_WINDOW_REF:
            DESKTOP_WINDOW_REF.move(new_x, new_y)

        self._send_json_response({"status": "ok", "new_x": new_x, "new_y": new_y})

    def _handle_api_chat(self):
        content_length = int(self.headers.get("Content-Length", 0))
        post_data = self.rfile.read(content_length)
        try:
            req_json = json.loads(post_data.decode("utf-8"))
            prompt = req_json.get("prompt", "")
            
            if not prompt:
                self._send_json_response({"error": "Empty prompt provided"}, status=400)
                return

            if self.conductor:
                response_text = self.conductor.process_user_event(prompt, debug=False)
                self._send_json_response({"response": response_text, "status": "success"})
            else:
                self._send_json_response({"response": f"Helix Subconscious Engine response to: {prompt}", "status": "mock"})
        except Exception as e:
            self._send_json_response({"error": f"Failed to process chat event: {e}"}, status=500)

    def _handle_api_ingest(self):
        try:
            form = cgi.FieldStorage(
                fp=self.rfile,
                headers=self.headers,
                environ={'REQUEST_METHOD': 'POST', 'CONTENT_TYPE': self.headers['Content-Type']}
            )
            
            uploaded_files = []
            total_chunks = 0
            
            if "files" in form:
                files = form["files"]
                if not isinstance(files, list):
                    files = [files]
                    
                for file_item in files:
                    if file_item.filename:
                        # Save temp file
                        temp_path = os.path.join(BASE_DIR, f"temp_{int(time.time())}_{file_item.filename}")
                        with open(temp_path, "wb") as f:
                            f.write(file_item.file.read())
                            
                        # Process ingestion & chunking
                        res = self.ingester.process_file_upload(temp_path, file_item.filename)
                        if os.path.exists(temp_path):
                            os.remove(temp_path)
                            
                        if res.get("success"):
                            uploaded_files.append(file_item.filename)
                            total_chunks += res.get("chunk_count", 0)

            # Reload mRAG adapter beliefs to include new chunks
            if self.conductor and self.conductor.researcher:
                self.conductor.researcher.mrag_adapter._load_helix_beliefs()

            self._send_json_response({
                "success": True,
                "files_processed": uploaded_files,
                "total_chunks": total_chunks
            })
        except Exception as e:
            self._send_json_response({"success": False, "error": str(e)}, status=500)

    def _handle_sse_stream(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        
        affect_label = "Deeply Focused & Analytical"
        if self.conductor and self.conductor.identity_compiler:
            affect_label = self.conductor.identity_compiler.affect_pipeline.state.label
            
        data = json.dumps({
            "thought": "Subconscious background pulse active.",
            "affect_label": affect_label,
            "expression": "happy"
        })
        try:
            self.wfile.write(f"event: pulse\ndata: {data}\n\n".encode("utf-8"))
            self.wfile.flush()
        except Exception:
            pass

    def _send_json_response(self, data: Dict[str, Any], status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))


def run_widget_web_server(port: int = 8080, conductor: Optional[SubconsciousConductor] = None):
    WidgetHTTPServerHandler.conductor = conductor
    server = HTTPServer(("0.0.0.0", port), WidgetHTTPServerHandler)
    print(f"\n=====================================================================")
    print(f" 🚀 HELIX DESKTOP FLOATING WIDGET SERVER RUNNING at http://localhost:{port}")
    print(f"=====================================================================\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Widget Web Server...")
        server.server_close()

if __name__ == "__main__":
    from subconscious_conductor import SubconsciousConductor
    conductor = SubconsciousConductor()
    run_widget_web_server(port=8080, conductor=conductor)
