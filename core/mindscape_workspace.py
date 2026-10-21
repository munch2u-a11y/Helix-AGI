"""Workspace embodiment for the existing native mind, not another agent loop.

These handlers are host actuators. Their presence alone proves neither a learned
RWKV motor decoder nor an agent's ability to choose and use them.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import time
import uuid
import signal
import threading

from habitus_ai.agent_workspace import AgentWorkspace
from habitus_ai.tools import ToolDefinition
from habitus_ai.types import OutputTrunk
from core.mindscape_intention import ABILITY_DESCRIPTIONS


class MindscapeWorkspace(AgentWorkspace):
    """Persistent position, metadata-only touch, real content and checked writes."""

    def __init__(self, root, store, *, home=None):
        self._execution_lock = threading.Lock()
        self._execution_process = None
        self._execution_cancelled = threading.Event()
        self.home = home
        self.dream_engine = None
        if home:
            previous_root = store.get_metadata("helix_agent_home_root", "")
            if previous_root != str(Path(root).resolve()):
                previous_position = store.get_metadata("agent_workspace_position", ".")
                store.set_metadata("helix_home_position_migration", json.dumps({
                    "previous_root": previous_root, "previous_position": previous_position,
                    "root": str(Path(root).resolve()), "position": "thinking"}))
                store.set_metadata("agent_workspace_position", "thinking")
                store.set_metadata("helix_agent_home_root", str(Path(root).resolve()))
            # A tool process is never restored as active across a restart.
            store.set_metadata("helix_home_module", "{}")
        super().__init__(root, store)

    def disengage(self, arguments=None):
        before = json.loads(self.store.get_metadata("helix_home_module", "{}"))
        self.store.set_metadata("helix_home_module", "{}")
        return {"disengaged": before.get("module"), "process_active": False}

    def active_module(self):
        return json.loads(self.store.get_metadata("helix_home_module", "{}"))

    def consume_module(self, receipt_id):
        if self.active_module().get("receipt_id") == receipt_id:
            return self.disengage()

    def observe_environment(self, pulse):
        scene = {"observation_id": f"home-sense:{uuid.uuid4().hex}", "time_ns": time.time_ns(),
                 "helix_pulse": pulse, "surroundings": self.sense({"path": "."}),
                 "room": (self.home or {}).get("rooms", {}).get(self.position, "A folder in my home."),
                 "active_module": self.active_module(), "content_opened": False}
        payload = json.dumps(scene, sort_keys=True, ensure_ascii=False)
        if self.home:
            from core.agent_home import write_home_json
            path = self.resolve_path("/intakes") / (scene["observation_id"].replace(":", "-") + ".json")
            write_home_json(path, scene)
        return scene, payload

    def _destination(self, supplied):
        raw = self._normalize_supplied_path(supplied)
        destination = super()._destination(raw)
        if self.home and (destination == self.root / "home.json" or
                          destination == self.root / "identity.json" or
                          destination == self.root / "bedroom/sleep.json" or
                          destination.is_relative_to(self.root / "modules") or
                          destination.is_relative_to(self.root / "intakes")):
            raise PermissionError("controller-owned home descriptors, modules and intakes cannot be replaced by an agent write")
        return destination

    def _normalize_supplied_path(self, supplied):
        raw = str(supplied).strip()
        path_obj = Path(raw)
        if path_obj.is_absolute():
            if path_obj.is_relative_to(self.root):
                return "/" + path_obj.relative_to(self.root).as_posix()
        return raw

    def resolve_path(self, supplied):
        raw = self._normalize_supplied_path(supplied)
        return super().resolve_path(raw)

    @staticmethod
    def _attributes(path):
        info = path.lstat()
        kind = ("symlink" if stat.S_ISLNK(info.st_mode) else
                "directory" if stat.S_ISDIR(info.st_mode) else
                "file" if stat.S_ISREG(info.st_mode) else "other")
        return {"name": path.name, "kind": kind, "size_bytes": info.st_size,
                "modified_ns": info.st_mtime_ns, "mode": stat.S_IMODE(info.st_mode),
                "extension_hint": path.suffix.lower() if kind == "file" else ""}

    def sense(self, arguments):
        path = self.resolve_path(arguments.get("path", "."))
        result = {"path": path.relative_to(self.root).as_posix(),
                  "position": self.position, **self._attributes(path),
                  "content_opened": False,
                  "interpretation": "filesystem attributes; extension is a hint, not verified content"}
        if path.is_dir():
            result["entries"] = [self._attributes(child) for child in sorted(path.iterdir())]
        return result

    def move(self, arguments):
        destination = self.resolve_path(arguments["path"])
        if not destination.is_dir():
            raise NotADirectoryError("movement requires a directory")
        self.disengage()
        before = self.position
        self.position = destination.relative_to(self.root).as_posix()
        self.store.set_metadata("agent_workspace_position", self.position)
        if self.store.get_metadata("agent_workspace_position") != self.position:
            raise OSError("workspace position did not persist")
        return {"previous_position": before, "position": self.position,
                "position_verified": True, "observed": self.sense({"path": "."})}

    def open(self, arguments):
        path = self.resolve_file(arguments["path"])
        before = path.stat()
        payload = path.read_bytes()
        after = path.stat()
        if (before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
            raise OSError("file changed while opening it; no stable content observation")
        if payload.startswith(b"%PDF-"):
            reader = shutil.which("pdftotext")
            if reader is None:
                raise RuntimeError("PDF opening requires the installed pdftotext reader")
            extracted = subprocess.run([reader, "-layout", "-", "-"], input=payload, capture_output=True)
            if extracted.returncode:
                raise ValueError("PDF text extraction failed: " + extracted.stderr.decode(errors="replace"))
            content, format_name = extracted.stdout.decode("utf-8"), "pdf_text"
            if not content.strip():
                raise ValueError("PDF has no extractable text; image/OCR reading is not connected")
        else:
            content, format_name = payload.decode("utf-8"), "utf8_text"
        return {"path": path.relative_to(self.root).as_posix(), "position": self.position,
                "size_bytes": len(payload), "modified_ns": after.st_mtime_ns,
                "sha256": hashlib.sha256(payload).hexdigest(),
                "content": content, "content_opened": True, "format": format_name,
                "complete": True, "text_extraction_only": format_name == "pdf_text"}

    def run(self, arguments):
        """Run an observed script inside the workshop filesystem/network scope.

        No runtime or output ceiling is imposed. A nonzero exit is an observed
        execution failure, never a completed task. The regular host is not
        mounted; only the interpreter, system libraries and workshop are.
        """
        path = self.resolve_file(arguments["path"])
        workshop = self.resolve_path("/workshop")
        if not path.is_relative_to(workshop):
            raise PermissionError("Python experiments must use a workshop script")
        if path.suffix != ".py":
            raise ValueError("this actuator executes Python scripts only")
        if arguments.get("expected_sha256") != hashlib.sha256(path.read_bytes()).hexdigest():
            raise ValueError("the current script hash is required before execution")
        current = (self.root / self.position).resolve()
        working = current if current.is_relative_to(workshop) else path.parent
        result = self._isolated([sys.executable, "-I", "/workspace/" + path.relative_to(workshop).as_posix()],
                                cwd="/workspace/" + working.relative_to(workshop).as_posix())
        observed = {"path": path.relative_to(self.root).as_posix(),
                    "sha256": arguments["expected_sha256"], "return_code": result.returncode,
                    "stdout": result.stdout, "stderr": result.stderr,
                    "execution_scope": "workshop only; isolated network and process namespace",
                    "interpreter": sys.executable, "runtime_limit": None, "output_limit": None}
        if result.returncode:
            raise RuntimeError("Python execution failed: " + json.dumps(observed, ensure_ascii=False))
        return observed

    def run_python(self, supplied):
        raise PermissionError("Host Python execution is disabled; use run with an observed hash and a workshop script")

    def _isolated(self, argv, *, cwd="/workspace", network=False, module_scripts=False, input_text=None):
        bwrap = shutil.which("bwrap")
        if bwrap is None:
            raise RuntimeError("isolated Python execution requires bubblewrap")
        command = [bwrap, "--die-with-parent", "--unshare-all", "--new-session", "--clearenv",
                   "--ro-bind", "/usr", "/usr", "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp"]
        for location in ("/bin", "/sbin", "/lib", "/lib64"):
            if Path(location).is_symlink():
                command += ["--symlink", os.readlink(location), location]
            elif Path(location).exists():
                command += ["--ro-bind", location, location]
        if Path("/etc/ld.so.cache").exists():
            command += ["--ro-bind", "/etc/ld.so.cache", "/etc/ld.so.cache"]
        environment = Path(sys.prefix).resolve()
        if not environment.is_relative_to("/usr"):
            command += ["--ro-bind", str(environment), str(environment)]
        # Only terminal/Python experiments receive a writable workshop. Web
        # scripts receive no home mount; their network access is declared.
        if network:
            command += ["--share-net"]
            for location in ("/etc/resolv.conf", "/etc/ssl/certs", "/etc/hosts"):
                if Path(location).exists():
                    command += ["--ro-bind", location, location]
            command += ["--tmpfs", "/workspace"]
        else:
            command += ["--bind", str(self.resolve_path("/workshop")), "/workspace"]
        if module_scripts:
            command += ["--ro-bind", str(self.resolve_path("/modules")), "/modules"]
        command += ["--chdir", cwd,
                    "--setenv", "PATH", "/usr/bin:/bin", "--setenv", "HOME", "/tmp",
                    "--setenv", "PYTHONDONTWRITEBYTECODE", "1", "--", *argv]
        if self._execution_cancelled.is_set():
            raise RuntimeError("Body shutdown requested; execution cancelled")
        with self._execution_lock:
            process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, text=True, start_new_session=True)
            self._execution_process = process
            if self._execution_cancelled.is_set():
                os.killpg(process.pid, signal.SIGKILL)
        try:
            stdout, stderr = process.communicate(input=input_text)
            if self._execution_cancelled.is_set():
                raise RuntimeError("Body shutdown interrupted script execution; no completion established")
            return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
        finally:
            with self._execution_lock:
                self._execution_process = None

    def cancel_execution(self):
        """Explicit lifecycle cancellation of this body's own process namespace."""
        self._execution_cancelled.set()
        with self._execution_lock:
            process = self._execution_process
            if process is not None and process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass

    def activate(self, arguments):
        if not self.home:
            raise RuntimeError("No agent home is installed")
        name, parameters = arguments["module"], arguments["parameters"]
        spec = self.home["modules"].get(name)
        if spec is None:
            raise ValueError("Unknown installed module")
        if self.home["modules_require_room"] and self.position != spec["room"]:
            raise PermissionError(f"Enter /{spec['room']} before activating {name}")
        if set(parameters) != set(spec["parameters"]) or not all(isinstance(v, str) for v in parameters.values()):
            raise ValueError("Module parameters do not match its installed contract")
        self.disengage()
        try:
            if name == "sleep":
                if self.dream_engine is None:
                    raise RuntimeError("The production dream engine is not attached")
                output = self.dream_engine.run_dream_cycle()
                if not isinstance(output, dict) or output.get("status") == "error" or output.get("errors", 0):
                    raise RuntimeError("Dream cycle failed: " + json.dumps(output, default=str))
            else:
                for script in (name, "web_read") if name == "web_search" else (name,):
                    installed = self.home["modules"][script]
                    path = self.resolve_file(f"/modules/{script}.py")
                    if hashlib.sha256(path.read_bytes()).hexdigest() != installed["sha256"]:
                        raise ValueError("Installed operational script has changed; activation refused")
                result = self._isolated([sys.executable, "-B", f"/modules/{name}.py"],
                                        network=spec["network"], module_scripts=True,
                                        input_text=json.dumps(parameters))
                if result.returncode:
                    raise RuntimeError(json.dumps({"module": name, "return_code": result.returncode,
                                                   "stdout": result.stdout, "stderr": result.stderr}))
                output = json.loads(result.stdout)
            active = {"module": name, "parameters": parameters, "process_active": False,
                      "focus": "result awaiting consumption", "network": spec["network"]}
            self.store.set_metadata("helix_home_module", json.dumps(active))
            return {**active, "output": output, "complete": True, "runtime_limit": None, "output_limit": None}
        except BaseException:
            self.disengage()
            raise


class NativeWorkspaceBody:
    """Attach actuators to ContinualMind's existing SELF authorization/return loop."""

    def __init__(self, native, root, *, home=None):
        self.native = native
        self.workspace = MindscapeWorkspace(root, native.mind.store, home=home)
        # ContinualMind installs its own host Python actuator. Rebind that
        # inherited route too, so it cannot bypass the workshop namespace.
        from dataclasses import replace
        inherited = native.tools.get_tool("ability:workspace-run-python")
        if inherited is not None:
            native.tools.register_tool(replace(inherited, handler=self.workspace.run,
                description=ABILITY_DESCRIPTIONS["run"],
                parameters={"path": {"type": "string"}, "expected_sha256": {"type": "string"}}))
        native.workspace = self.workspace
        self.abilities = {}
        for action, trunk in (("move", OutputTrunk.DO), ("sense", OutputTrunk.LOOK),
                              ("open", OutputTrunk.LOOK), ("write", OutputTrunk.DO),
                              ("mkdir", OutputTrunk.DO), ("run", OutputTrunk.DO),
                              ("activate", OutputTrunk.DO), ("disengage", OutputTrunk.DO)):
            ability_id = f"ability:helix-workspace-{action}"
            self.abilities[action] = ability_id
            native.tools.register_tool(ToolDefinition(
                tool_id=ability_id, trunk=trunk, label=f"Workspace {action}",
                description=ABILITY_DESCRIPTIONS[action], terms=(), parameters={},
                handler=getattr(self.workspace, action), opaque=True, bind_to_trunk=False,
                sensory_encoder=native._sensory_encoder(ability_id)))
            motives = (native.foundation["drives"]["inquiry"], native.foundation["drives"]["integrity"]) if trunk == OutputTrunk.LOOK else (
                native.foundation["drives"]["agency"], native.foundation["composites"]["responsible_action"])
            for motive in motives:
                native.mind.add_relation(motive, ability_id, side="output")

    def execute(self, action, arguments):
        """A proposal is not authority; only a current selected affordance can act."""
        if action not in self.abilities:
            raise ValueError(f"unknown workspace action: {action}")
        if action != "activate":
            self.workspace.disengage()
        ability_id = self.abilities[action]
        opportunity = self.native._ability_opportunity(ability_id, arguments)
        pulse = self.native.runtime.advance((opportunity,))
        self.native.latest_pulse = pulse
        affordance = self.native._affordance(pulse, ability_id)
        self.last_action_eligibility = ({"state": self.native.backend.dump_state(),
                                         "graph": self.native.backend._graph_vectors()}
                                        if self.native.backend.training_enabled else None)
        self.native._latest_tool_return_pulse = None
        receipt = self.native.tools.execute(ability_id, dict(arguments), affordance=affordance)
        if action == "activate" and self.workspace.active_module():
            active = self.workspace.active_module()
            active["receipt_id"] = receipt.receipt_id
            self.native.mind.store.set_metadata("helix_home_module", json.dumps(active))
        returned = self.native._latest_tool_return_pulse
        if returned is None or not receipt.return_record_id or not receipt.outcome_id:
            self.workspace.disengage()
            raise RuntimeError("native action has no settled sensory return; no completion established")
        self.native.latest_pulse = returned
        return {"proposal_pulse": pulse.cycle.cycle_id, "selected_affordance": ability_id,
                "return_pulse": returned.cycle.cycle_id, "receipt": receipt.to_dict()}
