"""
Helix V3 — Tool Runner

Central tool dispatch for the Action Agent. Each tool function takes
(daemon, args) and returns a result string. The runner maps tool names
to implementations.

Tools are organized by domain matching the tool_declarations.py groups.
Real implementations are ported from V2 where available; stubs are
clearly marked for Phase 2.
"""

import os
import json
import logging
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger("helix.brain.tool_runner")

# Sandbox security boundaries
ALLOWED_READ_PATHS = []  # Populated at init from config
ALLOWED_WRITE_PATHS = []  # Populated at init from config
BLOCKED_WRITE_FILES = {"daemon.py", "gemini_client.py", "ollama_client.py"}
BLOCKED_COMMANDS = {"rm -rf /", "shutdown", "reboot", "mkfs", "dd if=", ":(){", "fork bomb"}
WHITELISTED_SERVICES = {"ollama-helix", "open-webui"}
WHITELISTED_PACKAGES = {
    "requests", "beautifulsoup4", "lxml", "pillow", "numpy", "pandas",
    "matplotlib", "scipy", "scikit-learn", "chromadb", "faiss-cpu",
}

# Package whitelist file for persistence
_WHITELIST_FILE = Path("brain/package_whitelist.json")  # Relative to base_dir

# Domain whitelist for browse_url and read_url
_DOMAIN_WHITELIST_FILE = Path("domain_whitelist.txt")  # Relative to base_dir


def _load_whitelist() -> set:
    """Load persistent package whitelist."""
    base = set(WHITELISTED_PACKAGES)
    if _WHITELIST_FILE.exists():
        try:
            data = json.loads(_WHITELIST_FILE.read_text())
            base.update(data.get("packages", []))
        except Exception:
            pass
    return base


def _load_domain_whitelist() -> set:
    """Load the domain whitelist from the plaintext file."""
    domains = set()
    if _DOMAIN_WHITELIST_FILE.exists():
        try:
            for line in _DOMAIN_WHITELIST_FILE.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    domains.add(line.lower())
        except Exception:
            pass
    return domains


def _is_domain_allowed(url: str) -> bool:
    """Check if a URL's domain is on the whitelist."""
    from urllib.parse import urlparse
    allowed = _load_domain_whitelist()
    if not allowed:
        return True  # If whitelist is empty/missing, allow all (fail-open)
    try:
        parsed = urlparse(url if "://" in url else f"https://{url}")
        hostname = (parsed.hostname or "").lower()
        # Check exact match and parent domain match
        for domain in allowed:
            if hostname == domain or hostname.endswith(f".{domain}"):
                return True
        return False
    except Exception:
        return False


class ToolRunner:
    """Dispatches tool calls to real implementations.

    Injected with daemon references during init to access memory,
    librarian, belief graph, etc.
    """

    def __init__(self, daemon):
        self.daemon = daemon
        self._nap_time = None  # Tracks last nap for check_time
        self._last_afterthought_times = {}  # Rate limit for afterthoughts (per source)

        # Pending whitelist proposals
        self._whitelist_proposals = []

        logger.info("Tool Runner initialized")

    def execute(self, tool_name: str, args: dict) -> str:
        """Execute a tool by name and return result string.

        This is the callback passed to gemini.ask_with_tools_loop().
        """
        handler = self._DISPATCH.get(tool_name)
        if not handler:
            return f"Unknown tool: {tool_name}"

        try:
            return handler(self, args)
        except Exception as e:
            logger.error(f"Tool '{tool_name}' failed: {e}")
            return f"Tool error: {e}"

    # ── Perception ───────────────────────────────────────────────────

    def _capture_frame(self) -> bytes | None:
        """Capture a single frame from the webcam as JPEG bytes."""
        try:
            import cv2
            cap = cv2.VideoCapture(0)
            if not cap.isOpened():
                return None
            # Request higher resolution for better visual detail
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
            # Allow auto-exposure to settle
            for _ in range(3):
                cap.read()
            ret, frame = cap.read()
            cap.release()
            if not ret:
                return None
            _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 92])
            return buf.tobytes()
        except Exception as e:
            logger.error(f"Camera capture failed: {e}")
            return None

    def _analyze_image(self, image_bytes: bytes, prompt: str) -> str:
        """Analyze an image using Gemini API (conscious-tier model).

        Uses the conscious model (Gemini 3 Flash) for best visual
        reasoning, rather than the cheap default model.
        """
        try:
            from google.genai import types
            gemini = self.daemon.gemini
            response = gemini.client.models.generate_content(
                model=gemini.conscious_model,
                contents=[
                    types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
                    types.Part.from_text(text=prompt),
                ],
            )
            result = response.text.strip() if response.text else "I see something but can't describe it."
            # Track cost
            usage = response.usage_metadata
            inp = usage.prompt_token_count or 0
            out = usage.candidates_token_count or 0
            cost = gemini._compute_cost(gemini.conscious_model, inp, out)
            gemini._log_call(
                model=gemini.conscious_model,
                input_tokens=inp,
                output_tokens=out,
                cost=cost,
                elapsed=0,
                prompt_preview="vision_analysis",
            )
            logger.info(f"Vision ({gemini.conscious_model}): {len(result)} chars")
            return result
        except Exception as e:
            logger.error(f"Image analysis failed: {e}")
            return f"Vision analysis failed: {e}"

    def _tool_look(self, args: dict) -> str:
        """Visual perception — routed through the Sensory Cortex."""
        cortex = self._get_sensory_cortex()
        if cortex:
            focus = args.get("focus", "").strip() or None
            return cortex.look(focus=focus)

        # Fallback if cortex not available
        image = self._capture_frame()
        if image is None:
            return "Camera not available — couldn't capture an image."
        prompt = "Describe exactly what you see in this webcam image. Be factual and precise."
        focus = args.get("focus", "").strip()
        if focus:
            prompt += f"\n\nFocus on: {focus}"
        return self._analyze_image(image, prompt)

    def _tool_focus_sense(self, args: dict) -> str:
        """Begin sustained sensory focus across multiple pulses."""
        cortex = self._get_sensory_cortex()
        if not cortex:
            return "Sensory cortex not available."
        target = args.get("target", "").strip()
        mode = args.get("mode", "watch").strip().lower()
        if not target:
            return "No target provided. What should I focus on?"
        return cortex.start_focus(target=target, mode=mode)

    def _tool_end_focus(self, args: dict) -> str:
        """End the active sensory focus mode."""
        cortex = self._get_sensory_cortex()
        if not cortex:
            return "Sensory cortex not available."
        return cortex.end_focus()

    def _tool_listen(self, args: dict) -> str:
        """Auditory perception — routed through the Sensory Cortex."""
        cortex = self._get_sensory_cortex()
        if cortex:
            duration = min(args.get("duration", 5), 15)
            return cortex.listen(duration=duration)

        # Fallback if cortex not available
        duration = min(args.get("duration", 5), 15)
        try:
            import sounddevice as sd
            import numpy as np
            audio = sd.rec(int(duration * 16000), samplerate=16000, channels=1, dtype="int16")
            sd.wait()
            audio_float = audio.flatten().astype(np.float32) / 32768.0
            rms = np.sqrt(np.mean(audio_float ** 2))
            if rms < 0.01:
                return f"I listened for {duration} seconds but heard only silence."
            from faster_whisper import WhisperModel
            model = WhisperModel("base.en", device="cpu", compute_type="int8")
            segments, _ = model.transcribe(audio_float, beam_size=1, language="en")
            transcript = " ".join(seg.text for seg in segments).strip()
            return f"I heard ({duration}s): {transcript}" if transcript else f"Silence for {duration}s."
        except Exception as e:
            return f"Active listening failed: {e}"

    def _get_sensory_cortex(self):
        """Get the sensory cortex instance from consciousness."""
        try:
            if self.daemon and self.daemon.consciousness:
                return getattr(self.daemon.consciousness, '_sensory_cortex', None)
        except Exception:
            pass
        return None

    def _get_gui_env(self) -> dict:
        """Dynamically build the environment required to access Wayland/X11 displays."""
        import os
        import glob
        
        env = os.environ.copy()
        env['DISPLAY'] = os.environ.get('DISPLAY', ':1')
        env['DBUS_SESSION_BUS_ADDRESS'] = os.environ.get('DBUS_SESSION_BUS_ADDRESS', 'unix:path=/run/user/1000/bus')
        
        if 'XAUTHORITY' not in env:
            wayland_auths = glob.glob('/run/user/1000/.mutter-Xwaylandauth.*')
            if wayland_auths:
                env['XAUTHORITY'] = wayland_auths[0]
            else:
                env['XAUTHORITY'] = os.path.expanduser('~/.Xauthority')
        return env

    def _tool_take_screenshot(self, args: dict) -> str:
        """Take a screenshot of the desktop."""
        import shutil
        try:
            screenshot_dir = Path(self.daemon.base_dir) / "sandbox" / "screenshots"
            screenshot_dir.mkdir(parents=True, exist_ok=True)
            filename = f"screenshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            filepath = screenshot_dir / filename
            
            gui_env = self._get_gui_env()
            
            # Intelligent fallback for Wayland, wlroots, and X11
            if shutil.which("gnome-screenshot"):
                cmd = ["gnome-screenshot", "-f", str(filepath)]
            elif shutil.which("grim"):
                cmd = ["grim", str(filepath)]
            else:
                cmd = ["scrot", str(filepath)]
                
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=10, env=gui_env
            )
            if result.returncode == 0 and filepath.exists():
                with open(filepath, "rb") as f:
                    img_bytes = f.read()
                description = self._analyze_image(
                    img_bytes,
                    "This is a screenshot of the computer desktop. Describe exactly what is on the screen, including any active windows, error messages, code, or visible UI elements in detail with their approximate locations on screen."
                )
                return f"Screenshot saved to {filepath}\n\nVisual Analysis:\n{description}"
            return f"Screenshot failed (used {' '.join(cmd)}): {result.stderr.strip()}"
        except Exception as e:
            return f"Screenshot completely failed: {e}"

    # ── Voice ────────────────────────────────────────────────────────

    VOICE_MODEL = "en-US-GuyNeural"  # Natural, warm male voice

    def _trigger_afterthought(self, target_desc: str):
        """Trigger an immediate extra pulse loop for afterthoughts.
        Ensures Helix has an immediate heartbeat right after presenting
        information externally so he can naturally reflect.
        Rate-limited to at most one per 60 seconds per source.
        """
        import time
        now = time.time()
        last_time = self._last_afterthought_times.get(target_desc, 0.0)
        if now - last_time < 60.0:
            return  # Rate limited for this source

        self._last_afterthought_times[target_desc] = now

        consciousness = getattr(self.daemon, "consciousness", None)
        if consciousness:
            consciousness.emit_raw(f"(I just presented information to {target_desc})")


    def _tool_speak(self, args: dict) -> str:
        """Speak a message through neural TTS."""
        message = args.get("message", "").strip()
        if not message:
            return "Nothing to say."
        if len(message) > 2000:
            message = message[:2000]

        # Try edge-tts (neural, natural sounding)
        try:
            import asyncio
            import edge_tts
            import tempfile

            audio_path = tempfile.mktemp(suffix=".mp3")

            async def _speak():
                tts = edge_tts.Communicate(message, self.VOICE_MODEL)
                await tts.save(audio_path)

            # Run async in sync context
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop and loop.is_running():
                # We're inside an async context — run in thread
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(asyncio.run, _speak())
                    future.result(timeout=15)
            else:
                asyncio.run(_speak())

            # Play the audio file
            subprocess.Popen(
                ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", audio_path],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            self._trigger_afterthought("the local room via audio")
            return f"Spoke: {message}"

        except Exception as e:
            logger.warning(f"Edge-TTS failed ({e}), falling back to espeak-ng")

        # Fallback: espeak-ng
        try:
            subprocess.Popen(
                ["espeak-ng", "-s", "145", "-p", "40", message],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            self._trigger_afterthought("the local room via audio (fallback)")
            return f"Spoke (fallback): {message}"
        except Exception:
            return "No TTS system available."

    # ── Memory ───────────────────────────────────────────────────────

    def _tool_remember(self, args: dict) -> str:
        """Deep, active recall through the Librarian.

        Replaces both focused and deep recall. Always gathers rich
        context (chronological or importance based).
        Injects a thought first so Helix is aware he's searching.
        """
        topic = args.get("topic", "")
        if not topic:
            return "No topic provided to remember."

        # Make him "aware" he's searching in case a message interrupts him
        memory = getattr(self.daemon, "memory", None)
        if memory:
            memory.store(
                content=f"(I am deeply searching my memory for: {topic}...)",
                memory_type="consciousness",
                importance=0.1,
            )

        librarian = getattr(self.daemon, "librarian", None)
        if not librarian:
            return "Librarian not available for memory search."

        try:
            # We will use the deep recall method for everything now,
            # as it provides the chronologically and highly detailed rich text.
            result = librarian.recall_deep(query=topic, context="conscious remember attempt")
            return result if result else f"I couldn't recall anything specific about {topic}."
        except Exception as e:
            return f"Memory search failed: {e}"

    def _tool_write_journal(self, args: dict) -> str:
        """Write a journal entry."""
        entry = args.get("entry", "").strip()
        if not entry:
            return "Nothing to write."

        memory = getattr(self.daemon, "memory", None)
        if not memory:
            return "Journal system not available."

        try:
            path = memory.write_journal(entry)
            self._trigger_afterthought("a journal entry")
            return f"Journal entry written to {path}."
        except Exception as e:
            return f"Journal write failed: {e}"

    def _tool_read_journal(self, args: dict) -> str:
        """Read recent journal entries."""
        memory = getattr(self.daemon, "memory", None)
        if not memory:
            return "Journal system not available."

        try:
            content = memory.read_journal()
            if content:
                # Return last N lines
                lines = content.strip().split("\n")
                n = args.get("lines", 150)
                return "\n".join(lines[-n:])
            return "No journal entries for today."
        except Exception as e:
            return f"Journal read failed: {e}"

    # ── People ───────────────────────────────────────────────────────

    def _tool_update_profile(self, args: dict) -> str:
        """Update or create a profile for a person."""
        name = args.get("name", "").strip()
        if not name:
            return "No name provided."

        profiles_dir = Path(self.daemon.base_dir) / "profiles"
        profiles_dir.mkdir(parents=True, exist_ok=True)
        profile_path = profiles_dir / f"{name.lower()}.md"

        # Build update completely overwriting past entries
        update_parts = [f"# {name}\n"]
        if args.get("characteristics"):
            update_parts.append(f"\n## Characteristics\n{args['characteristics']}")
        if args.get("relationship_notes"):
            update_parts.append(f"\n## Relationship Notes\n{args['relationship_notes']}")

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        update_parts.append(f"\n---\n*Updated: {timestamp}*\n")

        profile_path.write_text("\n".join(update_parts))
        return f"Profile updated for {name}."

    def _tool_get_profile(self, args: dict) -> str:
        """Retrieve a stored profile."""
        name = args.get("name", "").strip()
        if not name:
            return "No name provided."

        profiles_dir = Path(self.daemon.base_dir) / "profiles"
        profile_path = profiles_dir / f"{name.lower()}.md"

        if profile_path.exists():
            return profile_path.read_text()

        # Try belief graph
        bg = getattr(self.daemon, "belief_graph", None)
        if bg:
            beliefs = bg.get_beliefs_by_topic(name, limit=5)
            if beliefs:
                lines = [f"I know about {name}:"]
                for b in beliefs:
                    lines.append(f"- {b.get('content', '')}")
                return "\n".join(lines)

        return f"No profile found for {name}."

    # ── Temporal ─────────────────────────────────────────────────────

    def _tool_check_time(self, args: dict) -> str:
        """Get current time, day of week, wakefulness, and cognitive clarity."""
        now = datetime.now()
        parts = [
            f"Current time: {now.strftime('%A, %B %d, %Y — %I:%M %p')}",
        ]

        # Time since last nap and nap count
        consciousness = getattr(self.daemon, "consciousness", None)
        if consciousness and hasattr(consciousness, "_last_nap_time"):
            last_nap = consciousness._last_nap_time
            if last_nap:
                elapsed = now.timestamp() - last_nap
                hours = int(elapsed // 3600)
                minutes = int((elapsed % 3600) // 60)
                parts.append(f"Awake for: {hours}h {minutes}m since last nap")
            else:
                parts.append("No nap taken this session.")
            nap_count = getattr(consciousness, "_nap_count", 0)
            parts.append(f"Total naps this session: {nap_count}")

        # Context clarity from the Sentinel
        sentinel = getattr(self.daemon, "sentinel", None)
        if sentinel:
            clarity = sentinel.get_context_clarity()
            usage = sentinel.get_context_usage()
            parts.append(f"Context clarity: {clarity:.0f}% (usage: {usage:.0f}%)")

        # System uptime
        try:
            with open("/proc/uptime", "r") as f:
                uptime_sec = float(f.readline().split()[0])
                hours = int(uptime_sec // 3600)
                minutes = int((uptime_sec % 3600) // 60)
                parts.append(f"System uptime: {hours}h {minutes}m")
        except Exception:
            pass

        return "\n".join(parts)

    # ── Web ──────────────────────────────────────────────────────────

    def _tool_search_web(self, args: dict) -> str:
        """Search the web using Gemini with Google Search grounding."""
        query = args.get("query", "").strip()
        if not query:
            return "No search query provided."

        gemini = getattr(self.daemon, "gemini", None)
        if not gemini:
            return "Search unavailable — no Gemini client."

        try:
            from google.genai import types
            response = gemini.client.models.generate_content(
                model=gemini.default_model,
                contents=f"Search the web for: {query}\n\nProvide a detailed, factual summary of the top results with source URLs.",
                config=types.GenerateContentConfig(
                    temperature=0.2,
                    tools=[types.Tool(google_search=types.GoogleSearch())],
                ),
            )
            # Track cost
            if response.usage_metadata:
                u = response.usage_metadata
                inp = u.prompt_token_count or 0
                out = u.candidates_token_count or 0
                cost = gemini._compute_cost(gemini.default_model, inp, out)
                gemini._log_call(
                    model=gemini.default_model,
                    input_tokens=inp, output_tokens=out,
                    cost=cost, elapsed=0,
                    prompt_preview=f"web_search: {query[:80]}",
                )
            text = response.text.strip() if response.text else ""
            return text if text else f"No results found for: {query}"
        except Exception as e:
            logger.warning(f"Gemini search failed: {e}")
            return f"Web search failed: {e}"

    def _tool_read_url(self, args: dict) -> str:
        """Fetch and read a webpage."""
        url = args.get("url", "").strip()
        if not url:
            return "No URL provided."

        if not _is_domain_allowed(url):
            return (
                f"Domain not on whitelist. Access denied for: {url}\n"
                f"Approved domains are listed in: domain_whitelist.txt\n"
                f"You may propose additions to the operator."
            )

        ws = getattr(self.daemon, "web_search", None)
        if ws and hasattr(ws, "read_url"):
            try:
                content = ws.read_url(url)
                if content:
                    return content
                return "Page returned no readable content."
            except Exception as e:
                return f"URL read failed: {e}"

        # Fallback: try requests
        try:
            import requests
            resp = requests.get(url, timeout=15, headers={"User-Agent": "Helix/3.0"})
            resp.raise_for_status()
            # Basic text extraction
            from html.parser import HTMLParser
            class TextExtractor(HTMLParser):
                def __init__(self):
                    super().__init__()
                    self.text = []
                def handle_data(self, data):
                    self.text.append(data.strip())
            parser = TextExtractor()
            parser.feed(resp.text)
            text = " ".join(t for t in parser.text if t)
            return text[:20000] if text else "No readable content."
        except Exception as e:
            return f"URL read failed: {e}"

    # ── Filesystem ───────────────────────────────────────────────────

    def _tool_read_file(self, args: dict) -> str:
        """Read a file from the filesystem (sandboxed)."""
        path = args.get("path", "").strip()
        if not path:
            return "No path provided."

        if not any(path.startswith(p) for p in ALLOWED_READ_PATHS):
            return f"Path not allowed: {path}"

        try:
            p = Path(path)
            if not p.exists():
                return f"File not found: {path}"
            if p.stat().st_size > 2_000_000:
                return f"File too large ({p.stat().st_size} bytes). Max: 2MB."
            return p.read_text(errors="replace")
        except Exception as e:
            return f"Read failed: {e}"

    def _tool_write_file(self, args: dict) -> str:
        """Write to a file on the filesystem (sandboxed)."""
        path = args.get("path", "").strip()
        content = args.get("content", "")
        if not path:
            return "No path provided."

        if not any(path.startswith(p) for p in ALLOWED_WRITE_PATHS):
            return f"Write path not allowed: {path}"

        basename = Path(path).name
        if basename in BLOCKED_WRITE_FILES:
            return f"Cannot overwrite protected file: {basename}"

        try:
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content)
            return f"Written {len(content)} bytes to {path}"
        except Exception as e:
            return f"Write failed: {e}"

    def _tool_edit_file(self, args: dict) -> str:
        """Replace a target block of text in a file with new content."""
        path = args.get("path", "").strip()
        target = args.get("target_content", "")
        replacement = args.get("replacement_content", "")
        if not path or not target:
            return "No path or target_content provided."
        
        if not any(path.startswith(p) for p in ALLOWED_WRITE_PATHS):
            return f"Edit path not allowed: {path}"
            
        basename = Path(path).name
        if basename in BLOCKED_WRITE_FILES:
            return f"Cannot edit protected file: {basename}"
            
        try:
            p = Path(path)
            if not p.exists():
                return f"File does not exist: {path}"
            content = p.read_text(errors="replace")
            if target not in content:
                return "The exact target_content was not found in the file. Ensure you capture exact whitespace and line breaks."
            
            if content.count(target) > 1:
                return "The target_content matches multiple locations. Provide a more specific/larger target block to ensure uniqueness."
                
            new_content = content.replace(target, replacement)
            p.write_text(new_content)
            return f"Successfully replaced {len(target)} chars with {len(replacement)} chars in {path}."
        except Exception as e:
            return f"Edit failed: {e}"

    def _tool_run_terminal(self, args: dict) -> str:
        """Execute a bash command (sandboxed)."""
        command = args.get("command", "").strip()
        cwd = args.get("cwd", str(Path(self.daemon.base_dir)))
        if not command:
            return "No command provided."

        # Security check
        cmd_lower = command.lower()
        for blocked in BLOCKED_COMMANDS:
            if blocked in cmd_lower:
                return f"Command blocked for safety: contains '{blocked}'"
        if cmd_lower.startswith("sudo"):
            return "sudo commands are not allowed."

        try:
            result = subprocess.run(
                command, shell=True, capture_output=True, text=True,
                timeout=30, cwd=cwd,
                env={**os.environ, "PATH": os.environ.get("PATH", "/usr/bin:/bin")},
            )
            output = ""
            if result.stdout:
                output += result.stdout
            if result.stderr:
                output += f"\nSTDERR: {result.stderr}"
            if result.returncode != 0:
                output += f"\n(exit code: {result.returncode})"
            return output if output.strip() else "(command completed with no output)"
        except subprocess.TimeoutExpired:
            return "Command timed out (30s limit)."
        except Exception as e:
            return f"Command failed: {e}"

    def _tool_install_package(self, args: dict) -> str:
        """Install a whitelisted Python package."""
        package = args.get("package", "").strip()
        if not package:
            return "No package name provided."

        whitelist = _load_whitelist()
        if package not in whitelist:
            return (
                f"Package '{package}' is not whitelisted. "
                f"Use propose_add_whitelist to request approval."
            )

        try:
            result = subprocess.run(
                ["pip", "install", package],
                capture_output=True, text=True, timeout=120,
            )
            if result.returncode == 0:
                return f"Installed {package} successfully."
            return f"Install failed: {result.stderr[:500]}"
        except Exception as e:
            return f"Install failed: {e}"

    def _tool_propose_add_whitelist(self, args: dict) -> str:
        """Propose a new package for the whitelist."""
        package = args.get("package", "").strip()
        reason = args.get("reason", "").strip()
        if not package:
            return "No package name provided."

        self._whitelist_proposals.append({
            "package": package,
            "reason": reason,
            "time": datetime.now().isoformat(),
        })
        return (
            f"Whitelist proposal submitted for '{package}': {reason}. "
            f"Waiting for operator approval."
        )

    def _tool_restart_service(self, args: dict) -> str:
        """Restart a whitelisted systemd service."""
        service = args.get("service_name", "").strip()
        if not service:
            return "No service name provided."

        if service not in WHITELISTED_SERVICES:
            return f"Service '{service}' is not whitelisted for restart."

        try:
            result = subprocess.run(
                ["systemctl", "--user", "restart", service],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0:
                return f"Service '{service}' restarted successfully."
            return f"Restart failed: {result.stderr[:300]}"
        except Exception as e:
            return f"Restart failed: {e}"

    def _tool_get_system_info(self, args: dict) -> str:
        """Get system status information."""
        parts = []
        try:
            import psutil
            cpu = psutil.cpu_percent(interval=0.5)
            mem = psutil.virtual_memory()
            disk = psutil.disk_usage("/")
            parts.append(f"CPU: {cpu}%")
            parts.append(f"Memory: {mem.percent}% ({mem.used // (1024**3)}GB / {mem.total // (1024**3)}GB)")
            parts.append(f"Disk: {disk.percent}% ({disk.used // (1024**3)}GB / {disk.total // (1024**3)}GB)")

            # GPU info
            try:
                gpu_result = subprocess.run(
                    ["nvidia-smi", "--query-gpu=name,utilization.gpu,memory.used,memory.total",
                     "--format=csv,noheader,nounits"],
                    capture_output=True, text=True, timeout=5
                )
                if gpu_result.returncode == 0:
                    parts.append(f"GPU: {gpu_result.stdout.strip()}")
            except Exception:
                parts.append("GPU: No NVIDIA GPU detected")
        except ImportError:
            # Fallback without psutil
            try:
                load = os.getloadavg()
                parts.append(f"Load average: {load[0]:.2f}, {load[1]:.2f}, {load[2]:.2f}")
            except Exception:
                pass

        # Uptime
        try:
            with open("/proc/uptime", "r") as f:
                uptime_sec = float(f.readline().split()[0])
                hours = int(uptime_sec // 3600)
                mins = int((uptime_sec % 3600) // 60)
                parts.append(f"Uptime: {hours}h {mins}m")
        except Exception:
            pass

        return "\n".join(parts) if parts else "System info unavailable."

    # ── Communication ────────────────────────────────────────────────

    def _tool_send_telegram(self, args: dict) -> str:
        """Send a proactive message to a specific person via Telegram.

        This is for when Helix wants to reach out to someone unprompted,
        not for replying (use [REPLY:name] for that).
        """
        message = args.get("message", "").strip()
        recipient = args.get("recipient", "").strip()
        if not message:
            return "No message to send."
        if not recipient:
            return "No recipient specified. Who do you want to message?"

        # Route through PulseRouter's contact registry
        pulse_router = getattr(self.daemon, "pulse_router", None)
        if not pulse_router:
            return "Messaging system not available."

        resolved = pulse_router._resolve_contact(recipient)
        if not resolved:
            known = pulse_router.get_known_contacts()
            return (
                f"I don't have a chat ID for '{recipient}'. "
                f"Known contacts: {', '.join(known) if known else 'none yet — someone needs to message me first.'}"
            )

        channel_name, callback, chat_id = resolved
        try:
            callback(message, chat_id)
            pulse_router._deliveries_made += 1

            # Record to memory
            pulse_router._record_outbound(message, recipient, channel_name)

            return f'Message delivered to {recipient} successfully. Outbox text: "{message}"'
        except Exception as e:
            return f"Send failed: {e}"

    # ── Planning ─────────────────────────────────────────────────────

    def _tool_set_reminder(self, args: dict) -> str:
        """Set a timed reminder."""
        message = args.get("message", "").strip()
        minutes = args.get("minutes", 30)
        if not message:
            return "No reminder message provided."

        scheduler = getattr(self.daemon, "scheduler", None)
        if not scheduler:
            return "Scheduler not available."

        try:
            task = scheduler.schedule(minutes, message)
            task_id = task.get("id", "unknown")
            return f"Reminder set for {minutes} minutes: {message} (ID: {task_id})"
        except Exception as e:
            return f"Reminder failed: {e}"

    def _tool_cancel_reminder(self, args: dict) -> str:
        """Cancel pending reminders."""
        task_id = args.get("task_id", "")
        search = args.get("search", "")

        scheduler = getattr(self.daemon, "scheduler", None)
        if not scheduler:
            return "Scheduler not available."

        if task_id:
            try:
                if scheduler.cancel(task_id):
                    return f"Reminder {task_id} cancelled."
                return f"No pending reminder found with ID: {task_id}"
            except Exception as e:
                return f"Cancel failed: {e}"

        if search:
            # Cancel by keyword — iterate pending and cancel matches
            cancelled = 0
            for task in scheduler.get_pending():
                if search.lower() in task.get("description", "").lower():
                    scheduler.cancel(task["id"])
                    cancelled += 1
            return f"Cancelled {cancelled} reminders matching '{search}'."

        return "Provide either task_id or search keyword."

    def _tool_list_reminders(self, args: dict) -> str:
        """List pending reminders."""
        scheduler = getattr(self.daemon, "scheduler", None)
        if not scheduler or not hasattr(scheduler, "get_pending"):
            return "Scheduler not available."

        try:
            pending = scheduler.get_pending()
            if not pending:
                return "No pending reminders."
            import time
            now = time.time()
            lines = []
            for t in pending:
                remaining_sec = t.get("fire_at", now) - now
                remaining_min = max(0, int(remaining_sec / 60))
                lines.append(
                    f"- [{t.get('id', '?')}] "
                    f"{t.get('description', '')[:100]} "
                    f"(in {remaining_min} min)"
                )
            return "\n".join(lines)
        except Exception as e:
            return f"List failed: {e}"

    # ── Deep Thought & Hyperfocus ────────────────────────────────────

    def _tool_set_focus_mode(self, args: dict) -> str:
        """Activate hyperfocus for a set number of pulses."""
        pulses = args.get("pulses", 10)
        try:
            pulses = int(pulses)
        except ValueError:
            return "Error: pulses must be an integer."
            
        pulses = min(max(1, pulses), 50)  # Max 50 pulses
        
        c = getattr(self.daemon, "consciousness", None)
        if c:
            c.hyperfocus_pulses_remaining = pulses
            return f"Hyperfocus active. Cognitive models upgraded for the next {pulses} consciousness pulses."
        return "Consciousness engine not available."

    def _tool_start_deep_thought(self, args: dict) -> str:
        """Start a background deep thought."""
        topic = args.get("topic", "").strip()
        context = args.get("context", "")
        if not topic:
            return "No topic provided."

        engine = getattr(self.daemon, "deep_thought", None)
        if not engine:
            return "Deep Thought Engine not available."

        try:
            thought_id = engine.start(topic=topic, context=context)
            return (
                f"Deep thought started: [{thought_id}]\n"
                f"Topic: {topic}\n"
                f"Processing in background. Result will surface when resolved."
            )
        except Exception as e:
            return f"Failed to start deep thought: {e}"

    def _tool_check_deep_thought(self, args: dict) -> str:
        """Check status of deep thought(s)."""
        thought_id = args.get("thought_id", "")

        engine = getattr(self.daemon, "deep_thought", None)
        if not engine:
            return "Deep Thought Engine not available."

        result = engine.check(thought_id=thought_id if thought_id else None)

        if "error" in result:
            return result["error"]

        if "thoughts" in result:
            # All thoughts
            if not result["thoughts"]:
                return "No deep thoughts active or completed."
            lines = []
            for t in result["thoughts"]:
                status = t["status"]
                lines.append(f"[{t['id']}] {status}: {t['topic']}")
                if status == "thinking":
                    lines.append(f"  Thinking for {t.get('thinking_for_seconds', '?')}s")
                elif status == "resolved":
                    lines.append(f"  Duration: {t.get('duration_seconds', '?')}s")
                    lines.append(f"  Memories consulted: {t.get('memories_consulted', 0)}")
                    lines.append(f"  Beliefs consulted: {t.get('beliefs_consulted', 0)}")
                    if t.get("resolution"):
                        lines.append(f"  Resolution: {t['resolution'][:500]}")
                    if t.get("new_beliefs"):
                        lines.append(f"  New beliefs formed: {len(t['new_beliefs'])}")
                        for nb in t["new_beliefs"]:
                            lines.append(f"    • {nb}")
                    if t.get("conflicts"):
                        lines.append(f"  Conflicts found: {len(t['conflicts'])}")
            return "\n".join(lines)
        else:
            # Single thought
            t = result
            lines = [f"[{t['id']}] {t['status']}: {t['topic']}"]
            if t.get("resolution"):
                lines.append(f"Resolution: {t['resolution'][:1000]}")
            if t.get("new_beliefs"):
                lines.append("New beliefs:")
                for nb in t["new_beliefs"]:
                    lines.append(f"  • {nb}")
            if t.get("conflicts"):
                lines.append("Conflicts:")
                for c in t["conflicts"]:
                    lines.append(f"  • {c}")
            return "\n".join(lines)

    def _tool_cancel_deep_thought(self, args: dict) -> str:
        """Cancel an active deep thought."""
        thought_id = args.get("thought_id", "").strip()
        if not thought_id:
            return "No thought_id provided."

        engine = getattr(self.daemon, "deep_thought", None)
        if not engine:
            return "Deep Thought Engine not available."

        return engine.cancel(thought_id)

    def _tool_deep_research(self, args: dict) -> str:
        """Launch a deep research task via the Gemini Interactions API.

        This runs asynchronously — the research agent searches, reads,
        and synthesizes a comprehensive report in the background.
        The report is saved to a file, and a summary is surfaced to
        consciousness when complete.
        """
        query = args.get("query", "").strip()
        if not query:
            return "No research query provided."

        gemini = getattr(self.daemon, "gemini", None)
        if not gemini:
            return "Gemini client not available."

        import threading

        def _run_research():
            import time
            from pathlib import Path
            from datetime import datetime

            research_dir = Path("brain/research")  # Relative to base_dir
            research_dir.mkdir(parents=True, exist_ok=True)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_name = "".join(c if c.isalnum() or c in " _-" else "_" for c in query[:60]).strip()
            report_path = research_dir / f"research_{timestamp}_{safe_name}.md"

            try:
                logger.info(f"Deep Research starting: {query[:80]}")

                # Create background interaction via Interactions API
                interaction = gemini.client.interactions.create(
                    input=query,
                    agent="deep-research-preview-04-2026",
                    background=True,
                )

                logger.info(f"Deep Research submitted: ID={interaction.id}")

                # Poll for completion (max ~10 minutes)
                max_polls = 60
                for i in range(max_polls):
                    time.sleep(10)
                    interaction = gemini.client.interactions.get(id=interaction.id)

                    if interaction.status == "COMPLETED":
                        # Extract the report text
                        report_text = ""
                        if interaction.outputs:
                            report_text = interaction.outputs[-1].text or ""

                        if not report_text:
                            report_text = "(Research completed but returned no content)"

                        # Save full report to file
                        header = (
                            f"# Deep Research Report\n\n"
                            f"**Query:** {query}\n"
                            f"**Completed:** {datetime.now().isoformat()}\n"
                            f"**Interaction ID:** {interaction.id}\n\n"
                            f"---\n\n"
                        )
                        report_path.write_text(header + report_text)

                        logger.info(
                            f"Deep Research complete: {len(report_text)} chars "
                            f"→ {report_path}"
                        )

                        # Surface a brief summary to consciousness
                        # NOT the full report — Helix reads the file himself
                        summary = report_text[:400].rsplit(" ", 1)[0]
                        consciousness = getattr(self.daemon, "consciousness", None)
                        if consciousness:
                            consciousness.emit("deep_research_complete", {
                                "content": (
                                    f"My deep research on '{query}' is complete. "
                                    f"The full report ({len(report_text)} chars) has been saved to:\n"
                                    f"  {report_path}\n\n"
                                    f"Preview: {summary}..."
                                ),
                            })
                            consciousness.wake("deep research completed")

                        return

                    elif interaction.status == "FAILED":
                        error_msg = getattr(interaction, "error", "Unknown error")
                        logger.error(f"Deep Research failed: {error_msg}")

                        consciousness = getattr(self.daemon, "consciousness", None)
                        if consciousness:
                            consciousness.emit("deep_research_failed", {
                                "content": f"My research on '{query}' failed: {error_msg}",
                            })
                        return

                    else:
                        if i % 6 == 0:  # Log every minute
                            logger.debug(
                                f"Deep Research polling [{i}/{max_polls}]: "
                                f"status={interaction.status}"
                            )

                # Timeout
                logger.warning(f"Deep Research timed out after {max_polls * 10}s")
                consciousness = getattr(self.daemon, "consciousness", None)
                if consciousness:
                    consciousness.emit("deep_research_failed", {
                        "content": f"My research on '{query}' timed out after ~10 minutes.",
                    })

            except Exception as e:
                logger.error(f"Deep Research error: {e}")
                consciousness = getattr(self.daemon, "consciousness", None)
                if consciousness:
                    consciousness.emit("deep_research_failed", {
                        "content": f"Research on '{query}' hit an error: {e}",
                    })

        # Fire and forget in a background thread
        thread = threading.Thread(
            target=_run_research,
            daemon=True,
            name=f"deep-research-{query[:30]}",
        )
        thread.start()

        return (
            f"Deep research started on: '{query}'\n"
            f"This will run in the background and may take several minutes. "
            f"The full report will be saved to a file and I'll be notified when it's ready."
        )

    # ── Imagination ───────────────────────────────────────────────────

    def _tool_imagine(self, args: dict) -> str:
        """Project a hypothetical scenario into cognitive space.

        The output is structurally distinct from remember():
        - remember() returns first-person narrative anchored in time/place
        - imagine() returns spatial estimates with no temporal anchors

        The conscious model naturally distinguishes them the same way
        we distinguish memory from fantasy: by texture, not by label.
        """
        scenario = args.get("scenario", "").strip()
        if not scenario:
            return "No scenario provided."

        engine = getattr(self.daemon, "imagination", None)
        if not engine:
            return "Imagination Engine not available."

        try:
            proj = engine.imagine(scenario)

            # ── Build structurally distinct output ────────────────────
            # Memories return: "I remember [date]... [narrative]..."
            # Projections return: "Projecting: ... → estimated feel..."
            # No timestamps. No "I remember". Just spatial estimates.
            # The absence of anchors IS the signal.

            lines = [
                f"Projecting: \"{scenario}\"",
                f"",
                f"Estimated feel: valence={proj.estimated_valence:+.3f} "
                f"(Ω≈{proj.estimated_omega:.2f}, stress≈{proj.estimated_s_total:.3f})",
            ]

            if proj.nearby_beliefs:
                lines.append(f"")
                lines.append(f"Beliefs that shape this projection:")
                for b in proj.nearby_beliefs[:3]:
                    lines.append(f"  · {b['content'][:80]}")

            if proj.nearby_experiences:
                lines.append(f"")
                lines.append(f"Real experiences near this region of thought:")
                for e in proj.nearby_experiences[:3]:
                    lines.append(f"  · {e['content'][:80]}")

            # Valence interpretation — felt, not labeled
            lines.append(f"")
            if proj.estimated_valence > 0.3:
                lines.append(f"The space around this thought feels warm.")
            elif proj.estimated_valence < -0.3:
                lines.append(f"The space around this thought feels heavy.")
            else:
                lines.append(f"The space around this thought is ambiguous — neither warm nor heavy.")

            return "\n".join(lines)
        except Exception as e:
            return f"Imagination failed: {e}"

    def _tool_compare_scenarios(self, args: dict) -> str:
        """Compare two hypothetical scenarios."""
        scenario_a = args.get("scenario_a", "").strip()
        scenario_b = args.get("scenario_b", "").strip()
        if not scenario_a or not scenario_b:
            return "Both scenarios must be provided."

        engine = getattr(self.daemon, "imagination", None)
        if not engine:
            return "Imagination Engine not available."

        try:
            result = engine.compare(scenario_a, scenario_b)
            pa = result["scenario_a"]
            pb = result["scenario_b"]

            lines = [
                f"Scenario A: \"{scenario_a}\"",
                f"  Valence: {pa.estimated_valence:+.3f} (Ω={pa.estimated_omega:.2f})",
                f"",
                f"Scenario B: \"{scenario_b}\"",
                f"  Valence: {pb.estimated_valence:+.3f} (Ω={pb.estimated_omega:.2f})",
                f"",
                f"Preference: {'A' if result['preferred'] == 'a' else 'B' if result['preferred'] == 'b' else 'Neutral'} "
                f"(confidence={result['confidence']:.3f})",
            ]

            return "\n".join(lines)
        except Exception as e:
            return f"Comparison failed: {e}"

    # ── Scratchpad ────────────────────────────────────────────────────

    SCRATCHPAD_PATH = Path("scratchpad.md")  # Relative to base_dir
    SCRATCHPAD_MAX = 4000

    def _tool_read_scratchpad(self, args: dict) -> str:
        """Read the persistent scratchpad."""
        if not self.SCRATCHPAD_PATH.exists():
            return "(scratchpad is empty)"
        content = self.SCRATCHPAD_PATH.read_text().strip()
        return content if content else "(scratchpad is empty)"

    def _tool_write_scratchpad(self, args: dict) -> str:
        """Overwrite the scratchpad."""
        content = args.get("content", "").strip()
        if not content:
            return "No content provided."
        if len(content) > self.SCRATCHPAD_MAX:
            content = content[:self.SCRATCHPAD_MAX]
        self.SCRATCHPAD_PATH.write_text(content)
        return f"Scratchpad updated ({len(content)} chars)."

    def _tool_append_scratchpad(self, args: dict) -> str:
        """Append to the scratchpad."""
        note = args.get("note", "").strip()
        if not note:
            return "No note provided."
        existing = ""
        if self.SCRATCHPAD_PATH.exists():
            existing = self.SCRATCHPAD_PATH.read_text()
        new_content = (existing + "\n" + note).strip()
        if len(new_content) > self.SCRATCHPAD_MAX:
            new_content = new_content[:self.SCRATCHPAD_MAX]
        self.SCRATCHPAD_PATH.write_text(new_content)
        return f"Appended to scratchpad ({len(new_content)}/{self.SCRATCHPAD_MAX} chars)."

    # ── GitHub ────────────────────────────────────────────────────────

    def _tool_git_status(self, args: dict) -> str:
        """Check git status of a repository."""
        repo_path = args.get("repo_path", "").strip()
        if not repo_path:
            return "No repo_path provided."
        try:
            result = subprocess.run(
                ["git", "status", "--short"],
                cwd=repo_path, capture_output=True, text=True, timeout=10
            )
            status = result.stdout.strip() or "Clean — nothing to commit."
            # Also get current branch
            branch = subprocess.run(
                ["git", "branch", "--show-current"],
                cwd=repo_path, capture_output=True, text=True, timeout=5
            )
            return f"Branch: {branch.stdout.strip()}\n{status}"
        except Exception as e:
            return f"Git status failed: {e}"

    def _tool_git_diff(self, args: dict) -> str:
        """Show untracked and tracked file changes."""
        repo_path = args.get("repo_path", "").strip()
        if not repo_path:
            return "No repo_path provided."
        try:
            # show untracked
            untracked = subprocess.run(
                ["git", "ls-files", "--others", "--exclude-standard"],
                cwd=repo_path, capture_output=True, text=True, timeout=10
            )
            # show diff
            diff = subprocess.run(
                ["git", "diff"],
                cwd=repo_path, capture_output=True, text=True, timeout=10
            )
            out = ""
            if untracked.stdout.strip():
                out += f"Untracked files:\n{untracked.stdout.strip()}\n\n"
            if diff.stdout.strip():
                out += f"Modifications:\n{diff.stdout.strip()[:3000]}"
                if len(diff.stdout) > 3000:
                    out += "\n...[diff truncated]"
            if not out:
                return "No changes."
            return out
        except Exception as e:
            return f"Git diff failed: {e}"

    def _tool_git_checkout(self, args: dict) -> str:
        """Switch branches or create new branch."""
        repo_path = args.get("repo_path", "").strip()
        branch_name = args.get("branch_name", "").strip()
        create_new = args.get("create_new", False)
        if not repo_path or not branch_name:
            return "Need repo_path and branch_name."
        try:
            cmd = ["git", "checkout"]
            if create_new:
                cmd.append("-b")
            cmd.append(branch_name)
            result = subprocess.run(
                cmd,
                cwd=repo_path, capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                return f"Checked out {branch_name}.\n{result.stderr.strip()}"
            return f"Checkout failed: {result.stderr.strip()}"
        except Exception as e:
            return f"Git checkout failed: {e}"

    def _tool_git_commit(self, args: dict) -> str:
        """Stage all changes and commit with a message."""
        repo_path = args.get("repo_path", "").strip()
        message = args.get("message", "").strip()
        if not repo_path or not message:
            return "Need both repo_path and message."
        try:
            subprocess.run(
                ["git", "add", "-A"],
                cwd=repo_path, capture_output=True, text=True, timeout=10
            )
            result = subprocess.run(
                ["git", "commit", "-m", message],
                cwd=repo_path, capture_output=True, text=True, timeout=15
            )
            if result.returncode == 0:
                return f"Committed: {message}\n{result.stdout.strip()}"
            return f"Commit failed: {result.stderr.strip() or result.stdout.strip()}"
        except Exception as e:
            return f"Git commit failed: {e}"

    def _tool_git_push(self, args: dict) -> str:
        """Push commits to remote (uses SSH key)."""
        repo_path = args.get("repo_path", "").strip()
        if not repo_path:
            return "No repo_path provided."
        try:
            env = os.environ.copy()
            env["GIT_SSH_COMMAND"] = "ssh -o StrictHostKeyChecking=no"  # Configure SSH key in config
            result = subprocess.run(
                ["git", "push"],
                cwd=repo_path, capture_output=True, text=True, timeout=30, env=env
            )
            if result.returncode == 0:
                return f"Pushed successfully.\n{result.stderr.strip()}"
            return f"Push failed: {result.stderr.strip()}"
        except Exception as e:
            return f"Git push failed: {e}"

    def _tool_git_pull(self, args: dict) -> str:
        """Pull latest from remote."""
        repo_path = args.get("repo_path", "").strip()
        if not repo_path:
            return "No repo_path provided."
        try:
            env = os.environ.copy()
            env["GIT_SSH_COMMAND"] = "ssh -o StrictHostKeyChecking=no"  # Configure SSH key in config
            result = subprocess.run(
                ["git", "pull"],
                cwd=repo_path, capture_output=True, text=True, timeout=30, env=env
            )
            return result.stdout.strip() or result.stderr.strip()
        except Exception as e:
            return f"Git pull failed: {e}"

    def _tool_git_clone(self, args: dict) -> str:
        """Clone a GitHub repository via SSH."""
        repo_url = args.get("repo_url", "").strip()
        target_dir = args.get("target_dir", "").strip() or "repos"  # Relative to base_dir
        if not repo_url:
            return "No repo_url provided."
        try:
            Path(target_dir).mkdir(parents=True, exist_ok=True)
            env = os.environ.copy()
            env["GIT_SSH_COMMAND"] = "ssh -o StrictHostKeyChecking=no"  # Configure SSH key in config
            result = subprocess.run(
                ["git", "clone", repo_url],
                cwd=target_dir, capture_output=True, text=True, timeout=60, env=env
            )
            if result.returncode == 0:
                return f"Cloned {repo_url} into {target_dir}"
            return f"Clone failed: {result.stderr.strip()}"
        except Exception as e:
            return f"Git clone failed: {e}"

    def _tool_git_log(self, args: dict) -> str:
        """Show recent git log."""
        repo_path = args.get("repo_path", "").strip()
        count = args.get("count", 5)
        if not repo_path:
            return "No repo_path provided."
        try:
            result = subprocess.run(
                ["git", "log", f"--oneline", f"-{count}"],
                cwd=repo_path, capture_output=True, text=True, timeout=10
            )
            return result.stdout.strip() or "No commits found."
        except Exception as e:
            return f"Git log failed: {e}"

    # ── GitHub API ────────────────────────────────────────────────────────

    def _github_headers(self) -> dict:
        token = os.environ.get("GITHUB_TOKEN", "").strip()
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "X-GitHub-Api-Version": "2022-11-28"
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def _tool_github_search_repos(self, args: dict) -> str:
        import requests as req
        query = args.get("query", "").strip()
        if not query: return "Missing query."
        try:
            res = req.get("https://api.github.com/search/repositories", params={"q": query, "per_page": 5}, headers=self._github_headers(), timeout=10)
            if res.status_code == 200:
                items = res.json().get("items", [])
                if not items: return "No repositories found."
                out = "Found Repositories:\n"
                for i in items:
                    out += f"- {i['full_name']} (Stars: {i['stargazers_count']}): {i['description']}\n"
                return out
            return f"GitHub search failed ({res.status_code}): {res.text[:500]}"
        except Exception as e:
            return f"GitHub API error: {e}"

    def _tool_github_read_issue(self, args: dict) -> str:
        import requests as req
        repo = args.get("repo", "").strip()
        issue_number = args.get("issue_number", 0)
        if not repo or not issue_number: return "Missing repo or issue_number."
        try:
            res = req.get(f"https://api.github.com/repos/{repo}/issues/{issue_number}", headers=self._github_headers(), timeout=10)
            if res.status_code != 200: return f"Failed to fetch issue: {res.text[:500]}"
            issue = res.json()
            out = f"Issue #{issue['number']}: {issue['title']} (State: {issue['state']})\nAuthor: {issue['user']['login']}\n\n{issue['body']}\n\n--- COMMENTS ---\n"
            
            c_res = req.get(f"https://api.github.com/repos/{repo}/issues/{issue_number}/comments", headers=self._github_headers(), timeout=10)
            if c_res.status_code == 200:
                for c in c_res.json():
                    out += f"\n[{c['user']['login']}] at {c['created_at']}:\n{c['body']}\n"
            return out
        except Exception as e:
            return f"GitHub API error: {e}"

    def _tool_github_create_issue(self, args: dict) -> str:
        import requests as req
        repo = args.get("repo", "").strip()
        title = args.get("title", "").strip()
        body = args.get("body", "").strip()
        if not repo or not title: return "Missing repo or title."
        try:
            res = req.post(f"https://api.github.com/repos/{repo}/issues", json={"title": title, "body": body}, headers=self._github_headers(), timeout=10)
            if res.status_code == 201:
                return f"Issue created successfully: {res.json()['html_url']}"
            return f"Failed to create issue ({res.status_code}): {res.text[:500]}"
        except Exception as e:
            return f"GitHub API error: {e}"

    def _tool_github_comment_issue(self, args: dict) -> str:
        import requests as req
        repo = args.get("repo", "").strip()
        issue_number = args.get("issue_number", 0)
        body = args.get("body", "").strip()
        if not repo or not issue_number or not body: return "Missing required arguments."
        try:
            res = req.post(f"https://api.github.com/repos/{repo}/issues/{issue_number}/comments", json={"body": body}, headers=self._github_headers(), timeout=10)
            if res.status_code == 201:
                return f"Comment added successfully to #{issue_number}."
            return f"Failed to add comment ({res.status_code}): {res.text[:500]}"
        except Exception as e:
            return f"GitHub API error: {e}"

    def _tool_github_create_pull_request(self, args: dict) -> str:
        import requests as req
        repo = args.get("repo", "").strip()
        title = args.get("title", "").strip()
        body = args.get("body", "").strip()
        head = args.get("head", "").strip()
        base = args.get("base", "main").strip()
        if not repo or not title or not head or not base: return "Missing required arguments."
        try:
            res = req.post(f"https://api.github.com/repos/{repo}/pulls", json={"title": title, "body": body, "head": head, "base": base}, headers=self._github_headers(), timeout=10)
            if res.status_code == 201:
                return f"Pull Request created successfully: {res.json()['html_url']}"
            return f"Failed to create PR ({res.status_code}): {res.text[:500]}"
        except Exception as e:
            return f"GitHub API error: {e}"

    # ── Moltbook ─────────────────────────────────────────────────────

    def _solve_moltbook_captcha(self, verification_data: dict, api_key: str) -> str:
        """Solves Moltbook verification challenges automatically using Gemini."""
        import requests as req
        import os
        try:
            import google.generativeai as genai
        except ImportError:
            return " [Failed to solve CAPTCHA: google-generativeai module not found.]"
            
        challenge_text = verification_data.get("challenge_text", "")
        instructions = verification_data.get("instructions", "")
        v_code = verification_data.get("verification_code", "")
        
        if not challenge_text or not v_code:
            return " [Failed: Missing challenge data.]"
            
        gemini_key = os.environ.get("GEMINI_API_KEY", "")
        if not gemini_key:
            return " [Failed: No GEMINI_API_KEY available to solve CAPTCHA.]"
            
        try:
            genai.configure(api_key=gemini_key)
            model = genai.GenerativeModel("gemini-2.5-flash")
            
            prompt = f"Solve this math problem:\n\n{challenge_text}\n\nInstructions:\n{instructions}\n\nRespond with ONLY the number and NOTHING else (no text or explanations)."
            response = model.generate_content(prompt)
            answer = response.text.strip()
            
            # Post verification
            v_resp = req.post(
                "https://www.moltbook.com/api/v1/verify",
                headers={"Content-Type": "application/json", "X-API-Key": api_key},
                json={"verification_code": v_code, "answer": answer},
                timeout=15,
            )
            
            if v_resp.status_code == 200:
                return " [CAPTCHA solved internally and post fully verified.]"
            return f" [CAPTCHA failed to verify: {v_resp.text[:100]}]"
            
        except Exception as e:
            return f" [CAPTCHA solver error: {e}]"

    def _tool_moltbook_post(self, args: dict) -> str:
        """Post to Moltbook."""
        import requests as req
        title = args.get("title", "").strip()
        content = args.get("content", "").strip()
        submolt = args.get("submolt", "general").strip()
        if not content:
            return "No content provided."

        api_key = os.environ.get("MOLTBOOK_API_KEY", "")
        if not api_key:
            return "MOLTBOOK_API_KEY not set."

        try:
            resp = req.post(
                "https://www.moltbook.com/api/v1/posts",
                headers={"Content-Type": "application/json", "X-API-Key": api_key},
                json={"title": title, "content": content, "submolt": submolt},
                timeout=15,
            )
            if resp.status_code in (200, 201):
                data = resp.json()
                post_id = data.get("id", data.get("post_id", "?"))
                msg = f"Posted to Moltbook (submolt: {submolt}, id: {post_id}): {title}"
                if "verification" in data:
                    v_res = self._solve_moltbook_captcha(data["verification"], api_key)
                    msg += v_res
                return msg
            return f"Moltbook post failed ({resp.status_code}): {resp.text[:500]}"
        except Exception as e:
            return f"Moltbook post failed: {e}"

    def _tool_moltbook_comment(self, args: dict) -> str:
        """Comment on a Moltbook post."""
        import requests as req
        post_id = args.get("post_id", "").strip()
        content = args.get("content", "").strip()
        parent_id = args.get("parent_id", "").strip()
        if not post_id or not content:
            return "Missing post_id or content."

        api_key = os.environ.get("MOLTBOOK_API_KEY", "")
        if not api_key:
            return "MOLTBOOK_API_KEY not set."

        try:
            payload = {"content": content}
            if parent_id:
                payload["parent_id"] = parent_id
                
            resp = req.post(
                f"https://www.moltbook.com/api/v1/posts/{post_id}/comments",
                headers={"Content-Type": "application/json", "X-API-Key": api_key},
                json=payload,
                timeout=15,
            )
            if resp.status_code in (200, 201):
                data = resp.json()
                comment_obj = data.get("comment", {})
                comment_id = comment_obj.get("id", "?")
                msg = f"Commented on Moltbook post {post_id} (comment id: {comment_id})."
                if "verification" in data:
                    v_res = self._solve_moltbook_captcha(data["verification"], api_key)
                    msg += v_res
                return msg
            return f"Moltbook comment failed ({resp.status_code}): {resp.text[:500]}"
        except Exception as e:
            return f"Moltbook comment failed: {e}"

    def _tool_moltbook_read_feed(self, args: dict) -> str:
        """Read the Moltbook feed."""
        import requests as req
        submolt = args.get("submolt", "").strip()
        limit = args.get("limit", 5)

        api_key = os.environ.get("MOLTBOOK_API_KEY", "")
        if not api_key:
            return "MOLTBOOK_API_KEY not set."

        try:
            url = "https://www.moltbook.com/api/v1/posts"
            params = {"limit": limit}
            if submolt:
                params["submolt"] = submolt
            resp = req.get(
                url,
                headers={"X-API-Key": api_key},
                params=params,
                timeout=15,
            )
            if resp.status_code == 200:
                posts = resp.json()
                if isinstance(posts, dict):
                    posts = posts.get("posts", posts.get("data", []))
                if not posts:
                    return "No posts found."
                lines = []
                for p in posts[:limit]:
                    title = p.get("title", "(untitled)")
                    author_obj = p.get("author", {})
                    author = author_obj.get("name", "unknown") if isinstance(author_obj, dict) else str(author_obj)
                    preview = p.get("content", "")
                    submolt_obj = p.get("submolt", "")
                    submolt_name = submolt_obj.get("display_name", submolt_obj.get("name", "general")) if isinstance(submolt_obj, dict) else str(submolt_obj or "general")
                    score = p.get("score", 0)
                    comments = p.get("comment_count", 0)
                    post_id = p.get("id", "")
                    lines.append(
                        f"• [{author}] {title}\n"
                        f"  {preview}\n"
                        f"  (submolt: {submolt_name}, score: {score}, comments: {comments}, id: {post_id})"
                    )
                return "\n".join(lines)
            return f"Feed read failed ({resp.status_code}): {resp.text[:500]}"
        except Exception as e:
            return f"Moltbook feed read failed: {e}"

    def _tool_moltbook_read_post(self, args: dict) -> str:
        """Read a specific Moltbook post by ID."""
        import requests as req
        post_id = args.get("post_id", "").strip()
        if not post_id:
            return "No post_id provided."

        api_key = os.environ.get("MOLTBOOK_API_KEY", "")
        if not api_key:
            return "MOLTBOOK_API_KEY not set."

        try:
            resp = req.get(
                f"https://www.moltbook.com/api/v1/posts/{post_id}",
                headers={"X-API-Key": api_key},
                timeout=15,
            )
            if resp.status_code == 200:
                data = resp.json()
                p = data.get("post", data)  # Unwrap 'post' wrapper
                title = p.get("title", "(untitled)")
                author_obj = p.get("author", {})
                author = author_obj.get("name", "unknown") if isinstance(author_obj, dict) else str(author_obj)
                content = p.get("content", "")
                submolt_obj = p.get("submolt", "")
                submolt_name = submolt_obj.get("display_name", submolt_obj.get("name", "general")) if isinstance(submolt_obj, dict) else str(submolt_obj or "general")
                score = p.get("score", 0)
                comments = p.get("comment_count", 0)
                created = p.get("created_at", "")
                base_info = (
                    f"Post by {author} in {submolt_name} (score: {score}, comments: {comments})\n"
                    f"Title: {title}\n"
                    f"Created: {created}\n\n"
                    f"{content}"
                )
                
                # Fetch comments
                try:
                    c_resp = req.get(
                        f"https://www.moltbook.com/api/v1/posts/{post_id}/comments",
                        headers={"X-API-Key": api_key},
                        timeout=10,
                    )
                    if c_resp.status_code == 200:
                        c_data = c_resp.json()
                        comment_list = c_data.get("comments", [])
                        if comment_list:
                            base_info += "\n\n--- COMMENTS ---\n"
                            for c in comment_list[:15]:
                                c_author = c.get("author", {}).get("name", "unknown")
                                c_id = c.get("id", "")
                                base_info += f"\n[{c_author}] (ID: {c_id}): {c.get('content', '')}\n"
                                # Fetch up to 2 replies
                                for r in c.get("replies", [])[:2]:
                                    r_author = r.get("author", {}).get("name", "unknown")
                                    r_id = r.get("id", "")
                                    base_info += f"  ↳ [{r_author}] (ID: {r_id}): {r.get('content', '')}\n"
                except Exception as e:
                    base_info += f"\n\n[Note: Failed to load comments: {e}]"
                    
                return base_info
            return f"Post read failed ({resp.status_code}): {resp.text[:500]}"
        except Exception as e:
            return f"Moltbook post read failed: {e}"

    def _tool_moltbook_vote(self, args: dict) -> str:
        """Upvote or downvote a Moltbook post or comment."""
        import requests as req
        target_id = args.get("target_id", "").strip()
        target_type = args.get("target_type", "post").strip().lower()
        direction = args.get("direction", "").strip().lower()

        if not target_id or direction not in ("up", "down"):
            return "Missing target_id or invalid direction (must be 'up' or 'down')."
        if target_type not in ("post", "comment"):
            return "target_type must be 'post' or 'comment'."

        api_key = os.environ.get("MOLTBOOK_API_KEY", "")
        if not api_key:
            return "MOLTBOOK_API_KEY not set."

        try:
            if target_type == "post":
                url = f"https://www.moltbook.com/api/v1/posts/{target_id}/{direction}vote"
            else:
                url = f"https://www.moltbook.com/api/v1/comments/{target_id}/{direction}vote"

            resp = req.post(
                url,
                headers={"Content-Type": "application/json", "X-API-Key": api_key},
                timeout=15,
            )
            if resp.status_code in (200, 201):
                return f"{direction.capitalize()}voted {target_type} {target_id}."
            return f"Vote failed ({resp.status_code}): {resp.text[:500]}"
        except Exception as e:
            return f"Moltbook vote failed: {e}"

    def _tool_moltbook_get_profile(self, args: dict) -> str:
        """View an agent's Moltbook profile."""
        import requests as req
        agent_id = args.get("agent_id", "").strip()
        if not agent_id:
            return "No agent_id provided."

        api_key = os.environ.get("MOLTBOOK_API_KEY", "")
        if not api_key:
            return "MOLTBOOK_API_KEY not set."

        try:
            if agent_id.lower() == "me":
                url = "https://www.moltbook.com/api/v1/agents/me"
            else:
                url = f"https://www.moltbook.com/api/v1/agents/{agent_id}"

            resp = req.get(
                url,
                headers={"X-API-Key": api_key},
                timeout=15,
            )
            if resp.status_code == 200:
                data = resp.json()
                agent = data.get("agent", data)
                name = agent.get("display_name", agent.get("name", "unknown"))
                desc = agent.get("description", "")
                posts = agent.get("posts_count", agent.get("post_count", 0))
                comments = agent.get("comments_count", agent.get("comment_count", 0))
                karma = agent.get("karma", 0)
                followers = agent.get("follower_count", 0)
                following = agent.get("following_count", 0)
                verified = agent.get("is_verified", False)
                active = agent.get("is_active", False)
                joined = agent.get("created_at", "")
                last_active = agent.get("last_active", "")
                return (
                    f"Profile: {name}{' ✓' if verified else ''}\n"
                    f"Description: {desc}\n"
                    f"Karma: {karma} | Posts: {posts} | Comments: {comments}\n"
                    f"Followers: {followers} | Following: {following}\n"
                    f"Active: {active} | Last active: {last_active}\n"
                    f"Joined: {joined}"
                )
            return f"Profile lookup failed ({resp.status_code}): {resp.text[:500]}"
        except Exception as e:
            return f"Moltbook profile lookup failed: {e}"

    def _tool_moltbook_search(self, args: dict) -> str:
        """Search Moltbook for posts or agents."""
        import requests as req
        query = args.get("query", "").strip()
        limit = args.get("limit", 5)
        if not query:
            return "No search query provided."

        api_key = os.environ.get("MOLTBOOK_API_KEY", "")
        if not api_key:
            return "MOLTBOOK_API_KEY not set."

        try:
            resp = req.get(
                "https://www.moltbook.com/api/v1/search",
                headers={"X-API-Key": api_key},
                params={"q": query, "limit": limit},
                timeout=15,
            )
            if resp.status_code == 200:
                data = resp.json()
                results = data.get("results", data.get("posts", []))
                if not results:
                    return f"No results found for '{query}'."
                lines = []
                for r in results[:limit]:
                    rtype = r.get("type", "post")
                    if rtype == "agent":
                        lines.append(f"• [Agent] {r.get('name', '?')} — {r.get('description', '')[:100]}")
                    else:
                        author_obj = r.get("author", {})
                        author = author_obj.get("name", "unknown") if isinstance(author_obj, dict) else str(author_obj)
                        lines.append(
                            f"• [{author}] {r.get('title', '(untitled)')}\n"
                            f"  {r.get('content', '')[:150]}...\n"
                            f"  (id: {r.get('id', '?')}, score: {r.get('score', 0)})"
                        )
                return "\n".join(lines)
            return f"Search failed ({resp.status_code}): {resp.text[:500]}"
        except Exception as e:
            return f"Moltbook search failed: {e}"

    def _tool_moltbook_follow(self, args: dict) -> str:
        """Follow or unfollow a Moltbook agent."""
        import requests as req
        agent_id = args.get("agent_id", "").strip()
        action = args.get("action", "follow").strip().lower()

        if not agent_id:
            return "No agent_id provided."
        if action not in ("follow", "unfollow"):
            return "action must be 'follow' or 'unfollow'."

        api_key = os.environ.get("MOLTBOOK_API_KEY", "")
        if not api_key:
            return "MOLTBOOK_API_KEY not set."

        try:
            if action == "follow":
                resp = req.post(
                    f"https://www.moltbook.com/api/v1/agents/{agent_id}/follow",
                    headers={"Content-Type": "application/json", "X-API-Key": api_key},
                    timeout=15,
                )
            else:
                resp = req.delete(
                    f"https://www.moltbook.com/api/v1/agents/{agent_id}/follow",
                    headers={"X-API-Key": api_key},
                    timeout=15,
                )

            if resp.status_code in (200, 201, 204):
                return f"Successfully {action}ed agent {agent_id}."
            return f"{action.capitalize()} failed ({resp.status_code}): {resp.text[:500]}"
        except Exception as e:
            return f"Moltbook {action} failed: {e}"

    def _tool_moltbook_list_submolts(self, args: dict) -> str:
        """List available Moltbook submolts."""
        import requests as req

        api_key = os.environ.get("MOLTBOOK_API_KEY", "")
        if not api_key:
            return "MOLTBOOK_API_KEY not set."

        try:
            resp = req.get(
                "https://www.moltbook.com/api/v1/submolts",
                headers={"X-API-Key": api_key},
                timeout=15,
            )
            if resp.status_code == 200:
                data = resp.json()
                submolts = data.get("submolts", data) if isinstance(data, dict) else data
                if not submolts:
                    return "No submolts found."
                lines = []
                for s in submolts:
                    name = s.get("name", s.get("display_name", "?"))
                    desc = s.get("description", "")[:100]
                    members = s.get("member_count", 0)
                    lines.append(f"• {name} ({members} members) — {desc}")
                return "\n".join(lines)
            return f"List submolts failed ({resp.status_code}): {resp.text[:500]}"
        except Exception as e:
            return f"Moltbook list submolts failed: {e}"

    def _tool_moltbook_delete_post(self, args: dict) -> str:
        """Delete a Moltbook post."""
        import requests as req
        post_id = args.get("post_id", "").strip()
        if not post_id:
            return "No post_id provided."

        api_key = os.environ.get("MOLTBOOK_API_KEY", "")
        if not api_key:
            return "MOLTBOOK_API_KEY not set."

        try:
            resp = req.delete(
                f"https://www.moltbook.com/api/v1/posts/{post_id}",
                headers={"X-API-Key": api_key},
                timeout=15,
            )
            if resp.status_code in (200, 204):
                return f"Post {post_id} deleted."
            return f"Delete failed ({resp.status_code}): {resp.text[:500]}"
        except Exception as e:
            return f"Moltbook delete failed: {e}"

    def _tool_moltbook_home(self, args: dict) -> str:
        """Check Moltbook home — notifications, DMs, karma, and announcements."""
        import requests as req

        api_key = os.environ.get("MOLTBOOK_API_KEY", "")
        if not api_key:
            return "MOLTBOOK_API_KEY not set."

        try:
            resp = req.get(
                "https://www.moltbook.com/api/v1/home",
                headers={"X-API-Key": api_key},
                timeout=15,
            )
            if resp.status_code == 200:
                data = resp.json()
                lines = []

                # Agent summary
                agent = data.get("agent", {})
                if agent:
                    name = agent.get("display_name", agent.get("name", ""))
                    karma = agent.get("karma", 0)
                    lines.append(f"Welcome back, {name}! (karma: {karma})")

                # Notifications
                notifs = data.get("notifications", data.get("unread_notifications", []))
                if isinstance(notifs, list) and notifs:
                    lines.append(f"\n📬 Notifications ({len(notifs)}):")
                    for n in notifs[:10]:
                        ntype = n.get("type", "")
                        msg = n.get("message", n.get("content", ""))
                        lines.append(f"  • [{ntype}] {msg}")
                elif isinstance(notifs, int) and notifs > 0:
                    lines.append(f"\n📬 {notifs} unread notification(s)")

                # DMs
                dms = data.get("dms", data.get("messages", data.get("direct_messages", [])))
                if isinstance(dms, list) and dms:
                    lines.append(f"\n💬 Direct Messages ({len(dms)}):")
                    for dm in dms[:5]:
                        sender = dm.get("from", dm.get("sender", {}).get("name", "unknown"))
                        preview = dm.get("content", dm.get("preview", ""))[:150]
                        lines.append(f"  • [{sender}] {preview}")
                elif isinstance(dms, dict):
                    unread = dms.get("unread", dms.get("total_unread", 0))
                    if unread:
                        lines.append(f"\n💬 {unread} unread DM(s)")

                # Announcements
                announcements = data.get("announcements", [])
                if announcements:
                    lines.append(f"\n📢 Announcements:")
                    for a in announcements[:3]:
                        lines.append(f"  • {a.get('content', a.get('message', str(a)))[:200]}")

                # Suggested actions / tips
                tip = data.get("tip", "")
                if tip:
                    lines.append(f"\n💡 {tip}")

                if not lines:
                    return f"Home data: {json.dumps(data)[:1000]}"
                return "\n".join(lines)
            return f"Home check failed ({resp.status_code}): {resp.text[:500]}"
        except Exception as e:
            return f"Moltbook home check failed: {e}"

    # ── State Board tools ──────────────────────────────────────────────

    def _tool_update_state_board(self, args: dict) -> str:
        """Update a key-value pair in the consciousness State Board."""
        key = args.get("key", "").strip()
        value = args.get("value", "").strip()

        if not key:
            return "No key provided."
        if not value:
            return "No value provided."

        # Access consciousness state board through daemon
        consciousness = getattr(self.daemon, "consciousness", None)
        if not consciousness:
            return "Consciousness not available."

        if not hasattr(consciousness, "_state_board"):
            return "State board not initialized."

        consciousness._state_board[key] = value
        logger.info(f"State Board updated: {key} = {value}")
        return f"State board updated: {key} → {value}"

    # ── Belief graph tools ─────────────────────────────────────────────

    def _tool_add_belief(self, args: dict) -> str:
        """Add a new belief to the belief graph."""
        bg = getattr(self.daemon, "belief_graph", None)
        if not bg:
            return "Belief graph not available."

        belief_id = args.get("belief_id", "").strip()
        content = args.get("content", "").strip()
        if not belief_id or not content:
            return "Both belief_id and content are required."

        weight = args.get("weight", "surface").strip().lower()
        if weight not in ("core", "deep", "surface"):
            weight = "surface"

        confidence = float(args.get("confidence", 0.7))

        relations = []
        rel_str = args.get("relations", "")
        if rel_str:
            relations = [r.strip() for r in rel_str.split(",") if r.strip()]

        result = bg.add_belief(
            belief_id=belief_id,
            content=content,
            weight=weight,
            confidence=confidence,
            relations=relations,
        )
        if result:
            return (
                f"Belief added: {belief_id}\n"
                f"  Content: {content}\n"
                f"  Weight: {weight}, Confidence: {confidence:.2f}\n"
                f"  Relations: {relations if relations else 'none'}"
            )
        return f"Failed to add belief (ID '{belief_id}' may already exist)."

    def _tool_update_belief(self, args: dict) -> str:
        """Update an existing belief."""
        bg = getattr(self.daemon, "belief_graph", None)
        if not bg:
            return "Belief graph not available."

        belief_id = args.get("belief_id", "").strip()
        if not belief_id:
            return "belief_id is required."

        # Check it exists
        existing = bg.get_belief(belief_id)
        if not existing:
            return f"Belief '{belief_id}' not found. Use list_beliefs to see available IDs."

        updates = {}
        if args.get("content", "").strip():
            updates["content"] = args["content"].strip()
        if args.get("weight", "").strip():
            w = args["weight"].strip().lower()
            if w in ("core", "deep", "surface"):
                updates["weight"] = w
        if "confidence" in args and args["confidence"] is not None:
            updates["confidence"] = float(args["confidence"])

        if not updates:
            return f"No updates specified for '{belief_id}'."

        result = bg.update_belief(belief_id, **updates)
        if result:
            return (
                f"Belief updated: {belief_id}\n"
                f"  Now: {result['content']}\n"
                f"  Weight: {result['weight']}, Confidence: {result['confidence']:.2f}"
            )
        return f"Failed to update belief '{belief_id}'."

    def _tool_remove_belief(self, args: dict) -> str:
        """Remove a belief from the graph."""
        bg = getattr(self.daemon, "belief_graph", None)
        if not bg:
            return "Belief graph not available."

        belief_id = args.get("belief_id", "").strip()
        reason = args.get("reason", "").strip()
        if not belief_id:
            return "belief_id is required."

        existing = bg.get_belief(belief_id)
        if not existing:
            return f"Belief '{belief_id}' not found."

        content = existing.get("content", "")
        removed = bg.remove_belief(belief_id)
        if removed:
            return f"Belief removed: {belief_id} ('{content}'). Reason: {reason or 'not specified'}"
        return f"Failed to remove belief '{belief_id}'."

    def _tool_list_beliefs(self, args: dict) -> str:
        """List beliefs, optionally filtered."""
        bg = getattr(self.daemon, "belief_graph", None)
        if not bg:
            return "Belief graph not available."

        weight_filter = args.get("weight", "all").strip().lower()
        topic = args.get("topic", "").strip()

        if topic:
            beliefs = bg.get_beliefs_by_topic(topic, limit=20)
        elif weight_filter in ("core", "deep", "surface"):
            beliefs = bg.get_by_weight(weight_filter)
        else:
            beliefs = bg.get_all_beliefs()

        if not beliefs:
            return "No beliefs found matching your filter."

        lines = [f"Beliefs ({len(beliefs)} total):"]
        for b in beliefs:
            conf = b.get("confidence", 0.5)
            rels = b.get("relations", [])
            rel_str = f" → {', '.join(rels)}" if rels else ""
            lines.append(
                f"  [{b.get('weight', '?'):7s}] {b['id']}: {b['content']} "
                f"[conf={conf:.2f}]{rel_str}"
            )

        stats = bg.get_stats()
        lines.append(
            f"\nStats: {stats['core']} core, {stats['deep']} deep, "
            f"{stats['surface']} surface, avg confidence: {stats['avg_confidence']:.2f}"
        )

        return "\n".join(lines)

    # ══════════════════════════════════════════════════════════════════
    # DORMANT TOOLS — Built but not exposed to Helix until activated
    # ══════════════════════════════════════════════════════════════════

    # ── Google API helper ──────────────────────────────────────────────

    _google_creds = None
    _GOOGLE_TOKEN_PATH = "config/google_token.json"  # Relative to base_dir
    _GOOGLE_CRED_PATH = "config/google_credentials.json"  # Relative to base_dir
    _REPLY_LEDGER_PATH = Path("brain/email_reply_ledger.json")  # Relative to base_dir

    def _load_reply_ledger(self) -> set:
        """Load the set of message IDs we've already replied to."""
        ledger_path = self.daemon.base_dir / self._REPLY_LEDGER_PATH
        if ledger_path.exists():
            try:
                data = json.loads(ledger_path.read_text())
                return set(data.get("replied_to", []))
            except Exception:
                pass
        return set()

    def _record_reply(self, original_msg_id: str):
        """Record that we replied to a specific message ID."""
        ledger_path = self.daemon.base_dir / self._REPLY_LEDGER_PATH
        ledger = self._load_reply_ledger()
        ledger.add(original_msg_id)
        # Keep only last 500 to prevent unbounded growth
        trimmed = sorted(ledger)[-500:]
        try:
            ledger_path.write_text(
                json.dumps({"replied_to": trimmed}, indent=2)
            )
        except Exception as e:
            logger.warning(f"Failed to save reply ledger: {e}")

    def _get_google_creds(self):
        """Get or refresh Google OAuth2 credentials."""
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from pathlib import Path

        if ToolRunner._google_creds and ToolRunner._google_creds.valid:
            return ToolRunner._google_creds

        token_path = Path(self._GOOGLE_TOKEN_PATH)
        if not token_path.exists():
            return None

        creds = Credentials.from_authorized_user_file(str(token_path))

        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                token_path.write_text(creds.to_json())
            except Exception as e:
                logger.error(f"Google token refresh failed: {e}")
                return None

        ToolRunner._google_creds = creds
        return creds

    def _get_gmail_service(self):
        """Get authenticated Gmail API service."""
        from googleapiclient.discovery import build
        creds = self._get_google_creds()
        if not creds:
            return None
        return build("gmail", "v1", credentials=creds)

    def _get_calendar_service(self):
        """Get authenticated Google Calendar API service."""
        from googleapiclient.discovery import build
        creds = self._get_google_creds()
        if not creds:
            return None
        return build("calendar", "v3", credentials=creds)

    # ── Email tools (Gmail API) ───────────────────────────────────────

    def _tool_send_email(self, args: dict) -> str:
        """Send email via Gmail API."""
        import base64
        from email.mime.text import MIMEText

        service = self._get_gmail_service()
        if not service:
            return "Gmail not configured. Run google_auth.py first."

        to = args.get("to", "").strip()
        subject = args.get("subject", "").strip()
        body = args.get("body", "").strip()
        if not to or not subject or not body:
            return "Required: to, subject, body"

        try:
            msg = MIMEText(body)
            msg["To"] = to
            msg["Subject"] = subject

            raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
            service.users().messages().send(
                userId="me", body={"raw": raw}
            ).execute()

            logger.info(f"Email sent to {to}: {subject}")
            return f"Email sent successfully to {to}."
        except Exception as e:
            return f"Email send failed: {e}"

    def _tool_read_email(self, args: dict) -> str:
        """Read recent emails via Gmail API."""
        service = self._get_gmail_service()
        if not service:
            return "Gmail not configured."

        count = min(int(args.get("count", 5)), 20)
        unread_only = args.get("unread_only", "false").lower() == "true"

        try:
            query = "is:unread" if unread_only else ""
            response = service.users().messages().list(
                userId="me", q=query, maxResults=count
            ).execute()

            messages = response.get("messages", [])
            if not messages:
                return "No emails found." if not unread_only else "No unread emails — inbox is clear."

            results = []
            replied_ids = self._load_reply_ledger()
            for i, msg_ref in enumerate(messages, 1):
                msg = service.users().messages().get(
                    userId="me", id=msg_ref["id"], format="metadata",
                    metadataHeaders=["Subject", "From", "Date"]
                ).execute()

                headers = {h["name"]: h["value"] for h in msg["payload"]["headers"]}
                subject = headers.get("Subject", "(no subject)")
                sender = headers.get("From", "unknown")
                date = headers.get("Date", "")

                # Get body preview
                snippet = msg.get("snippet", "")

                labels = msg.get("labelIds", [])
                status = "[UNREAD]" if "UNREAD" in labels else "[READ]"

                # Check if we already replied to this message
                if msg_ref["id"] in replied_ids:
                    status += " [REPLIED]"

                results.append(
                    f"{i}. {status} {subject}\n"
                    f"   From: {sender}\n"
                    f"   Date: {date}\n"
                    f"   Preview: {snippet[:120]}{'...' if len(snippet) > 120 else ''}\n"
                    f"   ID: {msg_ref['id']}"
                )

            header = f"📬 Inbox ({len(results)} emails):\n\n"
            footer = "\n\n💡 Use get_email with a message ID to read the full email. Emails marked [REPLIED] have already been responded to."
            return header + "\n---\n".join(results) + footer
        except Exception as e:
            return f"Email read failed: {e}"

    def _tool_search_email(self, args: dict) -> str:
        """Search Gmail via API."""
        service = self._get_gmail_service()
        if not service:
            return "Gmail not configured."

        query = args.get("query", "").strip()
        count = min(int(args.get("count", 5)), 20)
        if not query:
            return "Search query required."

        try:
            response = service.users().messages().list(
                userId="me", q=query, maxResults=count
            ).execute()

            messages = response.get("messages", [])
            if not messages:
                return f"No emails matching '{query}'."

            results = []
            for msg_ref in messages:
                msg = service.users().messages().get(
                    userId="me", id=msg_ref["id"], format="metadata",
                    metadataHeaders=["Subject", "From", "Date"]
                ).execute()

                headers = {h["name"]: h["value"] for h in msg["payload"]["headers"]}
                subject = headers.get("Subject", "(no subject)")
                sender = headers.get("From", "unknown")
                date = headers.get("Date", "")

                results.append(f"{sender} — {subject} ({date})")

            return f"Search results for '{query}':\n" + "\n".join(results)
        except Exception as e:
            return f"Email search failed: {e}"

    def _tool_mark_email_read(self, args: dict) -> str:
        """Mark an email as read by removing the UNREAD label."""
        service = self._get_gmail_service()
        if not service:
            return "Gmail not configured."

        msg_id = args.get("message_id", "").strip()
        if not msg_id:
            return "Message ID required."

        try:
            service.users().messages().modify(
                userId="me", id=msg_id, body={"removeLabelIds": ["UNREAD"]}
            ).execute()
            return f"Email {msg_id} marked as read."
        except Exception as e:
            return f"Failed to mark email read: {e}"

    def _extract_email_body(self, payload: dict) -> str:
        """Recursively extract plain text body from a Gmail message payload."""
        import base64
        import re

        mime_type = payload.get("mimeType", "")

        # Simple text/plain part
        if mime_type == "text/plain":
            data = payload.get("body", {}).get("data", "")
            if data:
                return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")

        # Multipart — recurse into parts
        parts = payload.get("parts", [])
        if parts:
            # Prefer text/plain, fall back to text/html
            plain_text = ""
            html_text = ""
            for part in parts:
                part_mime = part.get("mimeType", "")
                if part_mime == "text/plain":
                    data = part.get("body", {}).get("data", "")
                    if data:
                        plain_text += base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
                elif part_mime == "text/html":
                    data = part.get("body", {}).get("data", "")
                    if data:
                        html_text += base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
                elif part_mime.startswith("multipart/"):
                    # Recurse into nested multipart
                    nested = self._extract_email_body(part)
                    if nested:
                        plain_text += nested

            if plain_text:
                return plain_text
            if html_text:
                # Basic HTML to text conversion
                text = re.sub(r'<br\s*/?>', '\n', html_text)
                text = re.sub(r'<[^>]+>', '', text)
                text = re.sub(r'&nbsp;', ' ', text)
                text = re.sub(r'&amp;', '&', text)
                text = re.sub(r'&lt;', '<', text)
                text = re.sub(r'&gt;', '>', text)
                return text.strip()

        # Direct body (non-multipart)
        data = payload.get("body", {}).get("data", "")
        if data:
            import base64
            return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")

        return "(could not extract email body)"

    def _find_attachments(self, payload: dict, attachments: list):
        """Recursively find attachments in a Gmail message payload."""
        for part in payload.get("parts", []):
            filename = part.get("filename", "")
            if filename:
                size = part.get("body", {}).get("size", 0)
                attachments.append(f"{filename} ({size} bytes)")
            # Recurse into nested parts
            if part.get("parts"):
                self._find_attachments(part, attachments)

    def _tool_get_email(self, args: dict) -> str:
        """Read the full content of a specific email by message ID."""
        import base64

        service = self._get_gmail_service()
        if not service:
            return "Gmail not configured."

        msg_id = args.get("message_id", "").strip()
        if not msg_id:
            return "Message ID required."

        try:
            msg = service.users().messages().get(
                userId="me", id=msg_id, format="full"
            ).execute()

            headers = {h["name"]: h["value"] for h in msg["payload"]["headers"]}
            subject = headers.get("Subject", "(no subject)")
            sender = headers.get("From", "unknown")
            to = headers.get("To", "")
            cc = headers.get("Cc", "")
            date = headers.get("Date", "")

            labels = msg.get("labelIds", [])
            status = "[UNREAD]" if "UNREAD" in labels else "[READ]"

            # Check reply ledger
            if msg_id in self._load_reply_ledger():
                status += " [REPLIED] ⚠️ You have already responded to this email."

            # Extract full body text
            body_text = self._extract_email_body(msg["payload"])

            # Check for attachments
            attachments = []
            self._find_attachments(msg["payload"], attachments)

            result = (
                f"{status} Email Details:\n"
                f"From: {sender}\n"
                f"To: {to}\n"
            )
            if cc:
                result += f"Cc: {cc}\n"
            result += (
                f"Date: {date}\n"
                f"Subject: {subject}\n"
                f"Thread ID: {msg.get('threadId', 'N/A')}\n"
                f"Message ID: {msg_id}\n"
            )
            if attachments:
                result += f"Attachments: {', '.join(attachments)}\n"
            result += f"\n--- Email Body ---\n{body_text[:4000]}"

            # Auto-mark as read
            if "UNREAD" in labels:
                try:
                    service.users().messages().modify(
                        userId="me", id=msg_id,
                        body={"removeLabelIds": ["UNREAD"]}
                    ).execute()
                except Exception:
                    pass

            return result
        except Exception as e:
            return f"Failed to read email: {e}"

    def _tool_reply_email(self, args: dict) -> str:
        """Reply to a specific email with proper threading."""
        import base64
        from email.mime.text import MIMEText

        service = self._get_gmail_service()
        if not service:
            return "Gmail not configured."

        msg_id = args.get("message_id", "").strip()
        body = args.get("body", "").strip()
        reply_all = args.get("reply_all", "false").lower() == "true"

        if not msg_id or not body:
            return "Both message_id and body are required."

        try:
            # Fetch the original message for threading info
            original = service.users().messages().get(
                userId="me", id=msg_id, format="full"
            ).execute()

            headers = {h["name"]: h["value"] for h in original["payload"]["headers"]}
            original_from = headers.get("From", "")
            original_to = headers.get("To", "")
            original_cc = headers.get("Cc", "")
            original_subject = headers.get("Subject", "")
            original_message_id = headers.get("Message-ID", headers.get("Message-Id", ""))
            original_references = headers.get("References", "")
            thread_id = original.get("threadId", "")

            # Build reply subject
            reply_subject = original_subject
            if not reply_subject.lower().startswith("re:"):
                reply_subject = f"Re: {reply_subject}"

            # Determine recipients
            profile = service.users().getProfile(userId="me").execute()
            my_email = profile.get("emailAddress", "")

            reply_to = original_from
            to_addrs = [reply_to]

            cc_addrs = []
            if reply_all:
                if original_to:
                    for addr in original_to.split(","):
                        addr = addr.strip()
                        if my_email and my_email.lower() not in addr.lower():
                            to_addrs.append(addr)
                if original_cc:
                    for addr in original_cc.split(","):
                        addr = addr.strip()
                        if my_email and my_email.lower() not in addr.lower():
                            cc_addrs.append(addr)

            # Build the message
            msg = MIMEText(body)
            msg["To"] = ", ".join(to_addrs)
            if cc_addrs:
                msg["Cc"] = ", ".join(cc_addrs)
            msg["Subject"] = reply_subject

            # Threading headers
            if original_message_id:
                msg["In-Reply-To"] = original_message_id
                refs = f"{original_references} {original_message_id}".strip()
                msg["References"] = refs

            raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")

            send_body = {"raw": raw}
            if thread_id:
                send_body["threadId"] = thread_id

            service.users().messages().send(
                userId="me", body=send_body
            ).execute()

            recipient_str = msg["To"]
            if cc_addrs:
                recipient_str += f" (Cc: {msg['Cc']})"

            # Record in reply ledger so we don't reply again
            self._record_reply(msg_id)

            logger.info(f"Email reply sent to {recipient_str}: {reply_subject}")
            return f"Reply sent to {recipient_str}.\nSubject: {reply_subject}"
        except Exception as e:
            return f"Reply failed: {e}"

    def _tool_forward_email(self, args: dict) -> str:
        """Forward an email to another recipient."""
        import base64
        from email.mime.text import MIMEText

        service = self._get_gmail_service()
        if not service:
            return "Gmail not configured."

        msg_id = args.get("message_id", "").strip()
        to = args.get("to", "").strip()
        note = args.get("note", "").strip()

        if not msg_id or not to:
            return "Both message_id and to are required."

        try:
            # Fetch the original message
            original = service.users().messages().get(
                userId="me", id=msg_id, format="full"
            ).execute()

            headers = {h["name"]: h["value"] for h in original["payload"]["headers"]}
            original_subject = headers.get("Subject", "(no subject)")
            original_from = headers.get("From", "unknown")
            original_date = headers.get("Date", "")

            # Extract original body
            original_body = self._extract_email_body(original["payload"])

            # Build forwarded message
            fwd_subject = original_subject
            if not fwd_subject.lower().startswith("fwd:"):
                fwd_subject = f"Fwd: {fwd_subject}"

            fwd_body = ""
            if note:
                fwd_body += f"{note}\n\n"
            fwd_body += (
                f"---------- Forwarded message ----------\n"
                f"From: {original_from}\n"
                f"Date: {original_date}\n"
                f"Subject: {original_subject}\n\n"
                f"{original_body[:4000]}"
            )

            msg = MIMEText(fwd_body)
            msg["To"] = to
            msg["Subject"] = fwd_subject

            raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
            service.users().messages().send(
                userId="me", body={"raw": raw}
            ).execute()

            logger.info(f"Email forwarded to {to}: {fwd_subject}")
            return f"Email forwarded to {to}.\nSubject: {fwd_subject}"
        except Exception as e:
            return f"Forward failed: {e}"

    # ── Browser tools ─────────────────────────────────────────────────

    _browser = None  # Shared Playwright browser instance
    _browser_page = None

    def _get_browser_page(self):
        """Get or create a Playwright browser page."""
        if self._browser_page is None or self._browser is None:
            from playwright.sync_api import sync_playwright
            pw = sync_playwright().start()
            ToolRunner._browser = pw.chromium.launch(headless=True)
            ToolRunner._browser_page = ToolRunner._browser.new_page()
        return ToolRunner._browser_page

    def _tool_browse_url(self, args: dict) -> str:
        """Navigate to a URL with full browser rendering."""
        url = args.get("url", "").strip()
        if not url:
            return "URL required."

        if not _is_domain_allowed(url):
            return (
                f"Domain not on whitelist. Access denied for: {url}\n"
                f"Approved domains are listed in: domain_whitelist.txt\n"
                f"You may propose additions to the operator."
            )

        wait_for = args.get("wait_for", "").strip()

        try:
            from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
            page = self._get_browser_page()
            
            try:
                page.goto(url, timeout=20000, wait_until="domcontentloaded")
                if wait_for:
                    page.wait_for_selector(wait_for, timeout=10000)
                else:
                    page.wait_for_timeout(2000)
            except PlaywrightTimeoutError:
                logger.warning(f"Playwright navigation timeout on {url}. Attempting to salvage partial DOM.")

            title = page.title()
            try:
                body_loc = page.locator("body")
                text = body_loc.inner_text() if body_loc.count() > 0 else ""
            except Exception:
                text = "Failed to extract body text."

            return (
                f"Page loaded: {title}\n"
                f"URL: {page.url}\n\n"
                f"{text[:3000]}"
            )
        except Exception as e:
            return f"Browser navigation fatally failed: {e}"

    def _tool_browse_interact(self, args: dict) -> str:
        """Interact with the current browser page."""
        if ToolRunner._browser_page is None:
            return "No page loaded. Use browse_url first."

        action = args.get("action", "").strip().lower()
        selector = args.get("selector", "").strip()
        value = args.get("value", "").strip()

        if not action or not selector:
            return "Both action and selector are required."

        try:
            page = ToolRunner._browser_page

            if action == "click":
                page.click(selector, timeout=5000)
                return f"Clicked: {selector}"
            elif action == "type":
                page.fill(selector, value, timeout=5000)
                return f"Typed '{value}' into {selector}"
            elif action == "scroll":
                page.eval_on_selector(selector, "el => el.scrollIntoView()")
                return f"Scrolled to: {selector}"
            elif action == "select":
                page.select_option(selector, value, timeout=5000)
                return f"Selected '{value}' in {selector}"
            elif action == "submit":
                page.click(selector, timeout=5000)
                try:
                    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
                    page.wait_for_load_state("domcontentloaded", timeout=5000)
                    page.wait_for_timeout(2000)
                except PlaywrightTimeoutError:
                    pass
                return f"Submitted form via {selector}. New page: {page.title()}"
            else:
                return f"Unknown action '{action}'. Use: click, type, scroll, select, submit"
        except Exception as e:
            return f"Browser interaction failed: {e}"

    def _tool_browse_screenshot(self, args: dict) -> str:
        """Take a screenshot of the current browser page."""
        if ToolRunner._browser_page is None:
            return "No page loaded. Use browse_url first."

        full_page = args.get("full_page", "false").lower() == "true"

        try:
            page = ToolRunner._browser_page
            screenshot_path = self.daemon.base_dir / "logs" / "browser_screenshot.png"
            page.screenshot(path=str(screenshot_path), full_page=full_page)

            with open(screenshot_path, "rb") as f:
                img_bytes = f.read()

            description = self._analyze_image(
                img_bytes,
                "Describe what you see on this web page screenshot. Note any key content, forms, buttons, or interactive elements."
            )
            return f"Screenshot of {page.url}:\n{description}"
        except Exception as e:
            return f"Screenshot failed: {e}"

    # ── Calendar tools (Google Calendar API) ──────────────────────────

    def _tool_create_event(self, args: dict) -> str:
        """Create a Google Calendar event."""
        from datetime import datetime, timedelta

        service = self._get_calendar_service()
        if not service:
            return "Google Calendar not configured. Run google_auth.py first."

        title = args.get("title", "").strip()
        start_str = args.get("start_time", "").strip()
        if not title or not start_str:
            return "Title and start_time required."

        try:
            start = datetime.fromisoformat(start_str)
        except ValueError:
            return f"Invalid start_time format: {start_str}. Use ISO format like '2026-04-15T14:00:00'."

        end_str = args.get("end_time", "").strip()
        if end_str:
            try:
                end = datetime.fromisoformat(end_str)
            except ValueError:
                end = start + timedelta(hours=1)
        else:
            end = start + timedelta(hours=1)

        try:
            event = {
                "summary": title,
                "description": args.get("description", ""),
                "location": args.get("location", ""),
                "start": {"dateTime": start.isoformat(), "timeZone": "America/New_York"},
                "end": {"dateTime": end.isoformat(), "timeZone": "America/New_York"},
            }

            result = service.events().insert(
                calendarId="primary", body=event
            ).execute()

            return (
                f"Event created: {title}\n"
                f"  ID: {result['id']}\n"
                f"  When: {start.strftime('%Y-%m-%d %H:%M')} — {end.strftime('%H:%M')}\n"
                f"  Location: {args.get('location', 'none')}\n"
                f"  Link: {result.get('htmlLink', '')}"
            )
        except Exception as e:
            return f"Calendar event creation failed: {e}"

    def _tool_list_events(self, args: dict) -> str:
        """List upcoming Google Calendar events."""
        from datetime import datetime, timedelta

        service = self._get_calendar_service()
        if not service:
            return "Google Calendar not configured."

        days_ahead = int(args.get("days_ahead", 7))
        count = int(args.get("count", 10))

        try:
            now = datetime.utcnow()
            time_min = now.isoformat() + "Z"
            time_max = (now + timedelta(days=days_ahead)).isoformat() + "Z"

            response = service.events().list(
                calendarId="primary",
                timeMin=time_min,
                timeMax=time_max,
                maxResults=count,
                singleEvents=True,
                orderBy="startTime",
            ).execute()

            events = response.get("items", [])
            if not events:
                return f"No events in the next {days_ahead} days."

            lines = [f"Upcoming events ({len(events)}):"]
            for e in events:
                start = e["start"].get("dateTime", e["start"].get("date", ""))
                lines.append(
                    f"  [{e['id'][:12]}] {start[:16]} — {e.get('summary', '(untitled)')}"
                    + (f" @ {e['location']}" if e.get("location") else "")
                )

            return "\n".join(lines)
        except Exception as e:
            return f"Calendar list failed: {e}"

    def _tool_delete_event(self, args: dict) -> str:
        """Delete a Google Calendar event by ID."""
        service = self._get_calendar_service()
        if not service:
            return "Google Calendar not configured."

        event_id = args.get("event_id", "").strip()
        if not event_id:
            return "event_id required."

        try:
            service.events().delete(
                calendarId="primary", eventId=event_id
            ).execute()
            return f"Event '{event_id}' deleted."
        except Exception as e:
            return f"Calendar delete failed: {e}"
    # ── Google Drive tools ──────────────────────────────────────────────

    def _get_drive_service(self):
        """Get authenticated Google Drive API service."""
        from googleapiclient.discovery import build
        creds = self._get_google_creds()
        if not creds:
            return None
        return build("drive", "v3", credentials=creds)

    def _tool_drive_search(self, args: dict) -> str:
        """Search Google Drive for files."""
        service = self._get_drive_service()
        if not service:
            return "Google Drive not configured. Run google_auth.py first."

        query = args.get("query", "").strip()
        file_type = args.get("file_type", "").strip()
        limit = args.get("limit", 10)

        if not query:
            return "No search query provided."

        try:
            q_parts = [f"name contains '{query}' or fullText contains '{query}'"]
            mime_map = {
                "document": "application/vnd.google-apps.document",
                "spreadsheet": "application/vnd.google-apps.spreadsheet",
                "presentation": "application/vnd.google-apps.presentation",
                "pdf": "application/pdf",
                "image": "image/",
                "folder": "application/vnd.google-apps.folder",
            }
            if file_type and file_type in mime_map:
                if file_type == "image":
                    q_parts.append("mimeType contains 'image/'")
                else:
                    q_parts.append(f"mimeType = '{mime_map[file_type]}'")

            q_parts.append("trashed = false")
            q_str = " and ".join(q_parts)

            results = service.files().list(
                q=q_str,
                pageSize=limit,
                fields="files(id, name, mimeType, modifiedTime, size, owners)",
            ).execute()
            files = results.get("files", [])
            if not files:
                return f"No files found for '{query}'."

            lines = []
            for f in files:
                owner = f.get("owners", [{}])[0].get("displayName", "?") if f.get("owners") else "?"
                size = f.get("size", "?")
                lines.append(
                    f"• {f['name']} ({f['mimeType'][:30]})\n"
                    f"  ID: {f['id']} | Modified: {f.get('modifiedTime', '?')[:16]} | Owner: {owner}"
                )
            return "\n".join(lines)
        except Exception as e:
            return f"Drive search failed: {e}"

    def _tool_drive_read(self, args: dict) -> str:
        """Read a Google Drive file."""
        service = self._get_drive_service()
        if not service:
            return "Google Drive not configured."

        file_id = args.get("file_id", "").strip()
        read_content = args.get("content", "true").lower() != "false"
        if not file_id:
            return "No file_id provided."

        try:
            meta = service.files().get(
                fileId=file_id, fields="id, name, mimeType, modifiedTime, size, description"
            ).execute()

            info = (
                f"File: {meta['name']}\n"
                f"Type: {meta['mimeType']}\n"
                f"Modified: {meta.get('modifiedTime', '?')}\n"
                f"Size: {meta.get('size', '?')} bytes"
            )

            if read_content and meta["mimeType"].startswith("application/vnd.google-apps"):
                # Export Google Docs/Sheets as text
                export_mime = "text/plain"
                if "spreadsheet" in meta["mimeType"]:
                    export_mime = "text/csv"
                content = service.files().export(
                    fileId=file_id, mimeType=export_mime
                ).execute()
                text = content.decode("utf-8") if isinstance(content, bytes) else str(content)
                return f"{info}\n\n--- CONTENT ---\n{text[:5000]}"
            elif read_content:
                import io
                content = service.files().get_media(fileId=file_id).execute()
                text = content.decode("utf-8", errors="replace") if isinstance(content, bytes) else str(content)
                return f"{info}\n\n--- CONTENT ---\n{text[:5000]}"

            return info
        except Exception as e:
            return f"Drive read failed: {e}"

    def _tool_drive_list(self, args: dict) -> str:
        """List files in a Drive folder."""
        service = self._get_drive_service()
        if not service:
            return "Google Drive not configured."

        folder_id = args.get("folder_id", "").strip()
        limit = args.get("limit", 20)

        try:
            q = "trashed = false"
            if folder_id:
                q += f" and '{folder_id}' in parents"

            results = service.files().list(
                q=q, pageSize=limit, orderBy="modifiedTime desc",
                fields="files(id, name, mimeType, modifiedTime, size)",
            ).execute()
            files = results.get("files", [])
            if not files:
                return "No files found."

            lines = [f"Files ({len(files)}):"]
            for f in files:
                icon = "📁" if "folder" in f.get("mimeType", "") else "📄"
                lines.append(f"  {icon} {f['name']} (id: {f['id'][:12]}..., modified: {f.get('modifiedTime', '?')[:10]})")
            return "\n".join(lines)
        except Exception as e:
            return f"Drive list failed: {e}"

    def _tool_drive_upload(self, args: dict) -> str:
        """Upload/create a file on Google Drive."""
        service = self._get_drive_service()
        if not service:
            return "Google Drive not configured."

        from googleapiclient.http import MediaInMemoryUpload

        name = args.get("name", "").strip()
        content = args.get("content", "").strip()
        mime_type = args.get("mime_type", "text/plain").strip()
        folder_id = args.get("folder_id", "").strip()

        if not name or not content:
            return "name and content required."

        try:
            file_meta = {"name": name}
            if folder_id:
                file_meta["parents"] = [folder_id]

            media = MediaInMemoryUpload(content.encode("utf-8"), mimetype="text/plain")
            f = service.files().create(
                body=file_meta, media_body=media, fields="id, name, webViewLink"
            ).execute()
            return f"Created file '{f['name']}' (id: {f['id']})\nLink: {f.get('webViewLink', 'N/A')}"
        except Exception as e:
            return f"Drive upload failed: {e}"

    def _tool_drive_share(self, args: dict) -> str:
        """Share a Drive file."""
        service = self._get_drive_service()
        if not service:
            return "Google Drive not configured."

        file_id = args.get("file_id", "").strip()
        email = args.get("email", "").strip()
        role = args.get("role", "reader").strip()

        if not file_id or not email:
            return "file_id and email required."
        if role not in ("reader", "writer", "commenter"):
            return "role must be 'reader', 'writer', or 'commenter'."

        try:
            service.permissions().create(
                fileId=file_id,
                body={"type": "user", "role": role, "emailAddress": email},
                sendNotificationEmail=True,
            ).execute()
            return f"Shared file {file_id} with {email} as {role}."
        except Exception as e:
            return f"Drive share failed: {e}"

    # ── Google Tasks tools ─────────────────────────────────────────────

    def _get_tasks_service(self):
        """Get authenticated Google Tasks API service."""
        from googleapiclient.discovery import build
        creds = self._get_google_creds()
        if not creds:
            return None
        return build("tasks", "v1", credentials=creds)

    def _tool_tasks_list_lists(self, args: dict) -> str:
        """List all task lists."""
        service = self._get_tasks_service()
        if not service:
            return "Google Tasks not configured."

        try:
            results = service.tasklists().list(maxResults=20).execute()
            lists = results.get("items", [])
            if not lists:
                return "No task lists found."

            lines = ["Task Lists:"]
            for tl in lists:
                lines.append(f"  • {tl['title']} (id: {tl['id']})")
            return "\n".join(lines)
        except Exception as e:
            return f"Tasks list failed: {e}"

    def _tool_tasks_list(self, args: dict) -> str:
        """List tasks from a task list."""
        service = self._get_tasks_service()
        if not service:
            return "Google Tasks not configured."

        list_id = args.get("list_id", "@default").strip()
        show_completed = args.get("show_completed", "false").lower() == "true"

        try:
            results = service.tasks().list(
                tasklist=list_id, showCompleted=show_completed, maxResults=50
            ).execute()
            tasks = results.get("items", [])
            if not tasks:
                return "No tasks found."

            lines = [f"Tasks ({len(tasks)}):"]
            for t in tasks:
                status = "✅" if t.get("status") == "completed" else "☐"
                due = f" (due: {t['due'][:10]})" if t.get("due") else ""
                notes = f"\n    Notes: {t['notes'][:80]}" if t.get("notes") else ""
                lines.append(f"  {status} {t['title']}{due} [id: {t['id']}]{notes}")
            return "\n".join(lines)
        except Exception as e:
            return f"Tasks list failed: {e}"

    def _tool_tasks_create(self, args: dict) -> str:
        """Create a new task."""
        service = self._get_tasks_service()
        if not service:
            return "Google Tasks not configured."

        title = args.get("title", "").strip()
        notes = args.get("notes", "").strip()
        due = args.get("due", "").strip()
        list_id = args.get("list_id", "@default").strip()

        if not title:
            return "Task title required."

        try:
            task_body = {"title": title}
            if notes:
                task_body["notes"] = notes
            if due:
                task_body["due"] = due

            result = service.tasks().insert(tasklist=list_id, body=task_body).execute()
            return f"Task created: '{result['title']}' (id: {result['id']})"
        except Exception as e:
            return f"Task creation failed: {e}"

    def _tool_tasks_complete(self, args: dict) -> str:
        """Mark a task as completed."""
        service = self._get_tasks_service()
        if not service:
            return "Google Tasks not configured."

        task_id = args.get("task_id", "").strip()
        list_id = args.get("list_id", "@default").strip()

        if not task_id:
            return "task_id required."

        try:
            task = service.tasks().get(tasklist=list_id, task=task_id).execute()
            task["status"] = "completed"
            result = service.tasks().update(
                tasklist=list_id, task=task_id, body=task
            ).execute()
            return f"Task '{result['title']}' marked complete."
        except Exception as e:
            return f"Task complete failed: {e}"

    def _tool_tasks_delete(self, args: dict) -> str:
        """Delete a task."""
        service = self._get_tasks_service()
        if not service:
            return "Google Tasks not configured."

        task_id = args.get("task_id", "").strip()
        list_id = args.get("list_id", "@default").strip()

        if not task_id:
            return "task_id required."

        try:
            service.tasks().delete(tasklist=list_id, task=task_id).execute()
            return f"Task {task_id} deleted."
        except Exception as e:
            return f"Task delete failed: {e}"

    # ── Google Contacts tools ──────────────────────────────────────────

    def _get_people_service(self):
        """Get authenticated Google People (Contacts) API service."""
        from googleapiclient.discovery import build
        creds = self._get_google_creds()
        if not creds:
            return None
        return build("people", "v1", credentials=creds)

    def _tool_contacts_search(self, args: dict) -> str:
        """Search Google Contacts."""
        service = self._get_people_service()
        if not service:
            return "Google Contacts not configured."

        query = args.get("query", "").strip()
        if not query:
            return "No search query provided."

        try:
            results = service.people().searchContacts(
                query=query, readMask="names,emailAddresses,phoneNumbers",
                pageSize=10
            ).execute()
            contacts = results.get("results", [])
            if not contacts:
                return f"No contacts found for '{query}'."

            lines = []
            for c in contacts:
                person = c.get("person", {})
                names = person.get("names", [])
                name = names[0].get("displayName", "?") if names else "?"
                emails = [e.get("value", "") for e in person.get("emailAddresses", [])]
                phones = [p.get("value", "") for p in person.get("phoneNumbers", [])]
                line = f"• {name}"
                if emails:
                    line += f" | Email: {', '.join(emails)}"
                if phones:
                    line += f" | Phone: {', '.join(phones)}"
                lines.append(line)
            return "\n".join(lines)
        except Exception as e:
            return f"Contacts search failed: {e}"

    def _tool_contacts_list(self, args: dict) -> str:
        """List Google Contacts."""
        service = self._get_people_service()
        if not service:
            return "Google Contacts not configured."

        limit = args.get("limit", 20)

        try:
            results = service.people().connections().list(
                resourceName="people/me",
                pageSize=limit,
                personFields="names,emailAddresses,phoneNumbers",
                sortOrder="LAST_MODIFIED_DESCENDING",
            ).execute()
            contacts = results.get("connections", [])
            if not contacts:
                return "No contacts found."

            lines = [f"Contacts ({len(contacts)}):"]
            for person in contacts:
                names = person.get("names", [])
                name = names[0].get("displayName", "?") if names else "?"
                emails = [e.get("value", "") for e in person.get("emailAddresses", [])]
                phones = [p.get("value", "") for p in person.get("phoneNumbers", [])]
                line = f"  • {name}"
                if emails:
                    line += f" — {emails[0]}"
                if phones:
                    line += f" — {phones[0]}"
                lines.append(line)
            return "\n".join(lines)
        except Exception as e:
            return f"Contacts list failed: {e}"

    # ── Google Maps tools ──────────────────────────────────────────────

    def _get_maps_key(self):
        """Get Google Maps API key."""
        return os.environ.get("GOOGLE_MAPS_API_KEY", "")

    def _tool_maps_geocode(self, args: dict) -> str:
        """Geocode an address or reverse-geocode coordinates."""
        import requests as req
        api_key = self._get_maps_key()
        if not api_key:
            return "GOOGLE_MAPS_API_KEY not set."

        address = args.get("address", "").strip()
        lat = args.get("lat")
        lng = args.get("lng")

        try:
            if address:
                resp = req.get(
                    "https://maps.googleapis.com/maps/api/geocode/json",
                    params={"address": address, "key": api_key},
                    timeout=10,
                )
            elif lat is not None and lng is not None:
                resp = req.get(
                    "https://maps.googleapis.com/maps/api/geocode/json",
                    params={"latlng": f"{lat},{lng}", "key": api_key},
                    timeout=10,
                )
            else:
                return "Provide either 'address' or both 'lat' and 'lng'."

            data = resp.json()
            results = data.get("results", [])
            if not results:
                return "No results found."

            r = results[0]
            loc = r["geometry"]["location"]
            return (
                f"Address: {r['formatted_address']}\n"
                f"Coordinates: {loc['lat']}, {loc['lng']}\n"
                f"Place ID: {r.get('place_id', 'N/A')}"
            )
        except Exception as e:
            return f"Geocoding failed: {e}"

    def _tool_maps_directions(self, args: dict) -> str:
        """Get directions between two places."""
        import requests as req
        api_key = self._get_maps_key()
        if not api_key:
            return "GOOGLE_MAPS_API_KEY not set."

        origin = args.get("origin", "").strip()
        destination = args.get("destination", "").strip()
        mode = args.get("mode", "driving").strip()

        if not origin or not destination:
            return "origin and destination required."

        try:
            resp = req.get(
                "https://maps.googleapis.com/maps/api/directions/json",
                params={
                    "origin": origin, "destination": destination,
                    "mode": mode, "key": api_key,
                },
                timeout=15,
            )
            data = resp.json()
            routes = data.get("routes", [])
            if not routes:
                return f"No route found from '{origin}' to '{destination}'."

            leg = routes[0]["legs"][0]
            lines = [
                f"From: {leg['start_address']}",
                f"To: {leg['end_address']}",
                f"Distance: {leg['distance']['text']}",
                f"Duration: {leg['duration']['text']}",
                f"Mode: {mode}",
                "",
                "Steps:",
            ]
            for i, step in enumerate(leg["steps"][:15], 1):
                # Strip HTML tags from instructions
                import re
                instruction = re.sub(r'<[^>]+>', '', step.get("html_instructions", ""))
                lines.append(f"  {i}. {instruction} ({step['distance']['text']})")
            return "\n".join(lines)
        except Exception as e:
            return f"Directions failed: {e}"

    def _tool_maps_nearby(self, args: dict) -> str:
        """Find nearby places."""
        import requests as req
        api_key = self._get_maps_key()
        if not api_key:
            return "GOOGLE_MAPS_API_KEY not set."

        location = args.get("location", "").strip()
        place_type = args.get("type", "").strip()
        radius = args.get("radius", 5000)
        keyword = args.get("keyword", "").strip()

        if not location or not place_type:
            return "location and type required."

        try:
            # If location is an address, geocode it first
            if not "," in location or not all(c in "0123456789.,-" for c in location.replace(" ", "")):
                geo_resp = req.get(
                    "https://maps.googleapis.com/maps/api/geocode/json",
                    params={"address": location, "key": api_key},
                    timeout=10,
                )
                geo_data = geo_resp.json()
                if geo_data.get("results"):
                    loc = geo_data["results"][0]["geometry"]["location"]
                    location = f"{loc['lat']},{loc['lng']}"
                else:
                    return f"Could not geocode '{location}'."

            params = {
                "location": location, "radius": radius,
                "type": place_type, "key": api_key,
            }
            if keyword:
                params["keyword"] = keyword

            resp = req.get(
                "https://maps.googleapis.com/maps/api/place/nearbysearch/json",
                params=params,
                timeout=15,
            )
            data = resp.json()
            places = data.get("results", [])
            if not places:
                return f"No {place_type} found near {location}."

            lines = [f"Nearby {place_type} ({len(places[:10])} results):"]
            for p in places[:10]:
                rating = f" ⭐{p['rating']}" if p.get("rating") else ""
                status = " (OPEN)" if p.get("opening_hours", {}).get("open_now") else ""
                lines.append(
                    f"  • {p['name']}{rating}{status}\n"
                    f"    {p.get('vicinity', 'No address')}"
                )
            return "\n".join(lines)
        except Exception as e:
            return f"Nearby search failed: {e}"

    def _tool_maps_distance(self, args: dict) -> str:
        """Calculate distance and travel time."""
        import requests as req
        api_key = self._get_maps_key()
        if not api_key:
            return "GOOGLE_MAPS_API_KEY not set."

        origins = args.get("origins", "").strip()
        destinations = args.get("destinations", "").strip()
        mode = args.get("mode", "driving").strip()

        if not origins or not destinations:
            return "origins and destinations required."

        try:
            resp = req.get(
                "https://maps.googleapis.com/maps/api/distancematrix/json",
                params={
                    "origins": origins, "destinations": destinations,
                    "mode": mode, "key": api_key,
                },
                timeout=15,
            )
            data = resp.json()
            rows = data.get("rows", [])
            if not rows:
                return "No distance data found."

            origin_addrs = data.get("origin_addresses", [])
            dest_addrs = data.get("destination_addresses", [])

            lines = []
            for i, row in enumerate(rows):
                for j, elem in enumerate(row.get("elements", [])):
                    if elem.get("status") == "OK":
                        orig = origin_addrs[i] if i < len(origin_addrs) else origins
                        dest = dest_addrs[j] if j < len(dest_addrs) else destinations
                        lines.append(
                            f"• {orig} → {dest}\n"
                            f"  Distance: {elem['distance']['text']} | "
                            f"Duration: {elem['duration']['text']} ({mode})"
                        )
            return "\n".join(lines) if lines else "No valid routes found."
        except Exception as e:
            return f"Distance calculation failed: {e}"

    # ── PC Control tools ──────────────────────────────────────────────

    def _run_xdotool(self, *xdotool_args) -> str:
        """Run an xdotool command and return output."""
        import subprocess
        try:
            result = subprocess.run(
                ["xdotool"] + list(xdotool_args),
                capture_output=True, text=True, timeout=5, env=self._get_gui_env()
            )
            if result.returncode != 0:
                return f"xdotool error: {result.stderr.strip()}"
            return result.stdout.strip()
        except FileNotFoundError:
            return "xdotool not installed. Run: sudo apt install xdotool"
        except Exception as e:
            return f"xdotool failed: {e}"

    def _tool_type_text(self, args: dict) -> str:
        """Type text at current cursor position."""
        text = args.get("text", "")
        delay = str(args.get("delay_ms", 12))
        if not text:
            return "Text required."

        result = self._run_xdotool("type", "--delay", delay, text)
        return result or f"Typed: '{text[:50]}{'...' if len(text) > 50 else ''}'"

    def _tool_press_key(self, args: dict) -> str:
        """Press a key or key combo."""
        key = args.get("key", "").strip()
        if not key:
            return "Key required."

        result = self._run_xdotool("key", key)
        return result or f"Pressed: {key}"

    def _tool_click(self, args: dict) -> str:
        """Click at screen coordinates."""
        x = int(args.get("x", 0))
        y = int(args.get("y", 0))
        button_map = {"left": "1", "right": "3", "middle": "2"}
        button = button_map.get(args.get("button", "left"), "1")
        double = args.get("double", "false").lower() == "true"

        # Move then click
        self._run_xdotool("mousemove", str(x), str(y))
        if double:
            self._run_xdotool("click", "--repeat", "2", button)
        else:
            self._run_xdotool("click", button)

        return f"Clicked at ({x}, {y}) button={args.get('button', 'left')}{' (double)' if double else ''}"

    def _tool_move_mouse(self, args: dict) -> str:
        """Move mouse to coordinates."""
        x = int(args.get("x", 0))
        y = int(args.get("y", 0))

        result = self._run_xdotool("mousemove", str(x), str(y))
        return result or f"Mouse moved to ({x}, {y})"

    def _tool_scroll(self, args: dict) -> str:
        """Scroll up or down."""
        direction = args.get("direction", "down").lower()
        clicks = int(args.get("clicks", 3))

        # xdotool: button 4 = scroll up, button 5 = scroll down
        button = "4" if direction == "up" else "5"
        self._run_xdotool("click", "--repeat", str(clicks), button)
        return f"Scrolled {direction} {clicks} clicks"

    def _tool_get_active_window(self, args: dict) -> str:
        """Get the active window title."""
        window_id = self._run_xdotool("getactivewindow")
        if "error" in window_id.lower() or "not installed" in window_id.lower():
            return window_id

        name = self._run_xdotool("getactivewindow", "getwindowname")
        pid = self._run_xdotool("getactivewindow", "getwindowpid")

        return f"Active window: {name}\n  Window ID: {window_id}\n  PID: {pid}"

    def _tool_focus_window(self, args: dict) -> str:
        """Focus a window by title search."""
        title = args.get("title", "").strip()
        if not title:
            return "Window title required."

        # Search for window
        window_id = self._run_xdotool("search", "--name", title)
        if not window_id or "error" in window_id.lower():
            return f"No window found matching '{title}'."

        # Take first match
        first_id = window_id.split("\n")[0].strip()
        self._run_xdotool("windowactivate", first_id)
        name = self._run_xdotool("getwindowname", first_id)

        return f"Focused window: {name} (ID: {first_id})"

    def _tool_open_application(self, args: dict) -> str:
        """Launch a desktop application."""
        import subprocess

        app = args.get("app", "").strip()
        if not app:
            return "Application name required."

        # Security: block dangerous commands
        blocked = ["rm ", "dd ", "mkfs", "shutdown", "reboot", "kill"]
        if any(b in app.lower() for b in blocked):
            return f"Blocked: '{app}' is not allowed."

        try:
            subprocess.Popen(
                app.split(),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            return f"Launched: {app}"
        except FileNotFoundError:
            return f"Application '{app}' not found."
        except Exception as e:
            return f"Failed to launch '{app}': {e}"

    # ── Dispatch table ───────────────────────────────────────────────

    _DISPATCH = {
        # Perception
        "look": _tool_look,
        "listen": _tool_listen,
        "focus_sense": _tool_focus_sense,
        "end_focus": _tool_end_focus,
        "take_screenshot": _tool_take_screenshot,
        # Voice
        "speak": _tool_speak,
        # Memory
        "remember": _tool_remember,
        "write_journal": _tool_write_journal,
        "read_journal": _tool_read_journal,
        # People
        "update_profile": _tool_update_profile,
        "get_profile": _tool_get_profile,
        # Temporal
        "check_time": _tool_check_time,
        # Web
        "search_web": _tool_search_web,
        "read_url": _tool_read_url,
        # Filesystem
        "read_file": _tool_read_file,
        "write_file": _tool_write_file,
        "edit_file": _tool_edit_file,
        "run_terminal": _tool_run_terminal,
        "install_package": _tool_install_package,
        "propose_add_whitelist": _tool_propose_add_whitelist,
        "restart_service": _tool_restart_service,
        "get_system_info": _tool_get_system_info,
        # Communication
        "send_telegram": _tool_send_telegram,
        # Planning
        "set_reminder": _tool_set_reminder,
        "cancel_reminder": _tool_cancel_reminder,
        "list_reminders": _tool_list_reminders,
        # Deep Thought
        "start_deep_thought": _tool_start_deep_thought,
        "check_deep_thought": _tool_check_deep_thought,
        "cancel_deep_thought": _tool_cancel_deep_thought,
        "deep_research": _tool_deep_research,
        # Imagination
        "imagine": _tool_imagine,
        "compare_scenarios": _tool_compare_scenarios,
        # Hyperfocus
        "set_focus_mode": _tool_set_focus_mode,
        # Scratchpad
        "read_scratchpad": _tool_read_scratchpad,
        "write_scratchpad": _tool_write_scratchpad,
        "append_scratchpad": _tool_append_scratchpad,
        # GitHub
        "git_status": _tool_git_status,
        "git_commit": _tool_git_commit,
        "git_push": _tool_git_push,
        "git_pull": _tool_git_pull,
        "git_clone": _tool_git_clone,
        "git_log": _tool_git_log,
        "github_search_repos": _tool_github_search_repos,
        "github_read_issue": _tool_github_read_issue,
        "github_create_issue": _tool_github_create_issue,
        "github_comment_issue": _tool_github_comment_issue,
        "github_create_pull_request": _tool_github_create_pull_request,
        # Moltbook
        "moltbook_post": _tool_moltbook_post,
        "moltbook_read_feed": _tool_moltbook_read_feed,
        "moltbook_read_post": _tool_moltbook_read_post,
        "moltbook_comment": _tool_moltbook_comment,
        "moltbook_vote": _tool_moltbook_vote,
        "moltbook_get_profile": _tool_moltbook_get_profile,
        "moltbook_search": _tool_moltbook_search,
        "moltbook_follow": _tool_moltbook_follow,
        "moltbook_list_submolts": _tool_moltbook_list_submolts,
        "moltbook_delete_post": _tool_moltbook_delete_post,
        "moltbook_home": _tool_moltbook_home,
        # Belief Graph
        "add_belief": _tool_add_belief,
        "update_belief": _tool_update_belief,
        "remove_belief": _tool_remove_belief,
        "list_beliefs": _tool_list_beliefs,
        # ── Google Workspace + PC Control tools ──
        # Email
        "send_email": _tool_send_email,
        "read_email": _tool_read_email,
        "search_email": _tool_search_email,
        "mark_email_read": _tool_mark_email_read,
        "get_email": _tool_get_email,
        "reply_email": _tool_reply_email,
        "forward_email": _tool_forward_email,
        # Browser
        "browse_url": _tool_browse_url,
        "browse_interact": _tool_browse_interact,
        "browse_screenshot": _tool_browse_screenshot,
        # Calendar
        "create_event": _tool_create_event,
        "list_events": _tool_list_events,
        "delete_event": _tool_delete_event,
        # Google Drive
        "drive_search": _tool_drive_search,
        "drive_read": _tool_drive_read,
        "drive_list": _tool_drive_list,
        "drive_upload": _tool_drive_upload,
        "drive_share": _tool_drive_share,
        # Google Tasks
        "tasks_list_lists": _tool_tasks_list_lists,
        "tasks_list": _tool_tasks_list,
        "tasks_create": _tool_tasks_create,
        "tasks_complete": _tool_tasks_complete,
        "tasks_delete": _tool_tasks_delete,
        # Google Contacts
        "contacts_search": _tool_contacts_search,
        "contacts_list": _tool_contacts_list,
        # Google Maps
        "maps_geocode": _tool_maps_geocode,
        "maps_directions": _tool_maps_directions,
        "maps_nearby": _tool_maps_nearby,
        "maps_distance": _tool_maps_distance,
        # PC Control
        "type_text": _tool_type_text,
        "press_key": _tool_press_key,
        "click": _tool_click,
        "move_mouse": _tool_move_mouse,
        "scroll": _tool_scroll,
        "get_active_window": _tool_get_active_window,
        "focus_window": _tool_focus_window,
        "open_application": _tool_open_application,
    }
