"""Shared, explicit composition contract for CLI setup, wizard and main."""
from __future__ import annotations

import hashlib
import importlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
_ACTIVE_NATIVE_SOURCE = None


def configuration_path(root=ROOT):
    """Explicit launch profile, shared by every production config reader."""
    selected = Path(os.environ.get("HELIX_CONFIG_PATH") or Path(root) / "config/config.json").expanduser()
    selected = (selected if selected.is_absolute() else Path(root) / selected).resolve()
    if os.environ.get("HELIX_CONFIG_PATH") and not selected.is_file():
        raise FileNotFoundError(f"Explicit Helix launch profile is missing: {selected}")
    return selected


def defaults(root=ROOT):
    root = Path(root).resolve()
    from core.model_paths import default_native_source, default_rwkv_model
    rwkv_path = default_rwkv_model(root)
    mightymem_path = default_native_source(root)
    return {
        "composition": "mindscape",
        "pulse_mode": "standard",
        "local_provider": "rwkv",
        "local_model": str(rwkv_path),
        "llm_provider": "rwkv",
        "llm_model": str(rwkv_path),
        "local_context_window": 8192,
        "mindscape": {
            "package_path": mightymem_path,
            "rwkv_model": str(rwkv_path),
            "workspace": str(root),
            "home": str(root / "data/agent_home"),
            "modules_require_room": False,
            "device": "cpu",
            "gestation": "if_missing",
            "context_focus_profiles": {},
            "context_item_limit": 8,
            "context_item_limits": {},
            "gradient_learning": {
                "enabled": True,
                "train_rwkv_tail": False,
                "rwkv_tail_blocks": 1,
                "chunk_tokens": 128,
                "learning_rates": {"rwkv": 1e-5, "cortex": 1e-4, "interface": 3e-4},
                "gradient_clip_norm": 0.5,
            },
            "action_intent_source": "native_motor",
            "sensory_interval_seconds": 1.0,
            "pulse_interval_seconds": 1.0,
            "robustness": {},
        },
    }


def resolve(config, root=ROOT):
    composition = config.get("composition", "helix")
    if composition not in {"helix", "mindscape"}:
        raise ValueError(f"Unknown composition: {composition!r}; choose mindscape or helix explicitly")
    if composition == "helix":
        return None
    result = defaults(root)
    result.update(config)
    result["mindscape"] = {**defaults(root)["mindscape"], **config.get("mindscape", {})}
    base_learning = defaults(root)["mindscape"]["gradient_learning"]
    requested_learning = config.get("mindscape", {}).get("gradient_learning", {})
    if not isinstance(requested_learning, dict) or set(requested_learning) - set(base_learning):
        raise ValueError("mindscape.gradient_learning contains unknown settings")
    rates = requested_learning.get("learning_rates", {})
    if not isinstance(rates, dict) or set(rates) - set(base_learning["learning_rates"]):
        raise ValueError("gradient learning rates must name rwkv, cortex or interface")
    learning = {**base_learning, **requested_learning,
                "learning_rates": {**base_learning["learning_rates"], **rates}}
    result["mindscape"]["gradient_learning"] = learning
    if result.get("pulse_mode") != "standard":
        raise ValueError("Mindscape requires the standard Helix PulseLoop; dual mode is a different composition")
    if result.get("local_provider") not in {"ollama", "rwkv", "bicameral_rwkv"}:
        raise ValueError("Mindscape requires local Ollama or RWKV foreground")
    if result.get("llm_provider", "ollama") not in {"ollama", "rwkv", "bicameral_rwkv"}:
        raise ValueError("Mindscape uses Ollama or RWKV; select composition=helix for a different foreground provider")
    if result["mindscape"]["device"] != "cpu":
        raise ValueError("The native ContinualRwkv joint bridge is CPU-only; select device=cpu")
    if result["mindscape"]["gestation"] not in {"if_missing", "resume_only"}:
        raise ValueError("gestation must be if_missing or resume_only")
    if result["mindscape"]["action_intent_source"] not in {"native_motor", "granite_private", "rwkv_bicameral", "bicameral_rwkv"}:
        raise ValueError("action_intent_source must be native_motor")
    # Migrate old launch files to the body route; speech no longer dispatches.
    result["mindscape"]["action_intent_source"] = "native_motor"
    # The legacy speech-to-task hook belongs to a different action composition.
    requested_tasks = os.environ.get("HELIX_TASK_COGNITION", "off").strip().lower()
    if requested_tasks not in {"", "0", "false", "no", "off"}:
        raise ValueError("Mindscape requires HELIX_TASK_COGNITION=off; use composition=helix for task cognition")
    result["task_cognition_mode"] = "off"
    if not isinstance(result["mindscape"]["modules_require_room"], bool):
        raise ValueError("modules_require_room must be a boolean")
    import math
    for key in ("enabled", "train_rwkv_tail"):
        if type(learning[key]) is not bool:
            raise ValueError(f"gradient_learning.{key} must be a boolean")
    for key, minimum in (("chunk_tokens", 2), ("rwkv_tail_blocks", 1)):
        if type(learning[key]) is not int or learning[key] < minimum:
            raise ValueError(f"gradient_learning.{key} must be an integer >= {minimum}")
    for value in [learning["gradient_clip_norm"], *learning["learning_rates"].values()]:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError("Gradient learning rates and clipping norm must be finite positive values")
    cadence = float(result["mindscape"]["sensory_interval_seconds"])
    if not math.isfinite(cadence) or cadence <= 0:
        raise ValueError("sensory_interval_seconds must be finite and positive (filesystem observation cadence)")
    pulse_cadence = float(result["mindscape"]["pulse_interval_seconds"])
    if not math.isfinite(pulse_cadence) or pulse_cadence < 0:
        raise ValueError("pulse_interval_seconds must be finite and nonnegative (delay between completed awake pulses)")
    if int(result["local_context_window"]) <= 0:
        raise ValueError("local_context_window must be positive")
    limits = result["mindscape"]["context_item_limits"]
    if not isinstance(limits, dict) or any(not isinstance(key, str) or not key for key in limits):
        raise ValueError("mindscape.context_item_limits must map exact local_model values to item budgets")
    for item_limit in [result["mindscape"]["context_item_limit"], *limits.values()]:
        if item_limit is not None and (type(item_limit) is not int or item_limit < 1):
            raise ValueError("mindscape.context_item_limit must be a positive integer or null")
    result["mindscape"]["context_item_limit"] = limits.get(
        result["local_model"], result["mindscape"]["context_item_limit"])
    from core.robustness import options
    options(result)
    from core.context_focus import resolve_profiles
    resolve_profiles(result["mindscape"]["context_focus_profiles"])
    for key in ("package_path", "rwkv_model", "workspace", "home"):
        path = Path(result["mindscape"][key]).expanduser()
        if not path.is_absolute():
            path = Path(root) / path
        result["mindscape"][key] = str(path.resolve())
    return result


def activate(config):
    """Validate paths and select the declared source before importing neural code."""
    settings = resolve(config)
    if settings is None:
        return None
    module = settings["mindscape"]
    package = Path(module["package_path"])
    for relative in ("context_loom/engine.py", "habitus_ai/continual_mind.py"):
        if not (package / relative).is_file():
            raise RuntimeError(f"Full mindscape cannot start: missing {package / relative}")
    if not Path(module["rwkv_model"], "model.safetensors.index.json").is_file():
        raise RuntimeError(f"Full mindscape cannot start: RWKV weights missing at {module['rwkv_model']}")
    if not Path(module["workspace"]).is_dir():
        raise RuntimeError(f"Mindscape workspace does not exist: {module['workspace']}")
    from packaging.version import Version
    if Version(importlib.metadata.version("transformers")) < Version("5.15"):
        raise RuntimeError("Pinned RWKV requires transformers>=5.15; install requirements-mindscape.txt in the Helix venv")
    activate_native_source(package)
    # Native ContinualMind selects auto internally. Mask compute devices before
    # torch is imported; the audited bridge constructs its tensors on CPU.
    if "torch" in sys.modules and sys.modules["torch"].cuda.is_initialized():
        raise RuntimeError("Restart before loading Mindscape: GPU torch was already initialized")
    for key in ("CUDA_VISIBLE_DEVICES", "HIP_VISIBLE_DEVICES", "ROCR_VISIBLE_DEVICES"):
        os.environ[key] = ""
    os.environ["HELIX_SEMANTIC_STRICT"] = "1"
    if os.environ.get("HELIX_UNIFIED_RAG", "1").lower() in {"0", "false", "no", "off"}:
        raise RuntimeError("Full mindscape requires HELIX_UNIFIED_RAG; mRAG cannot be disabled")
    if os.environ.get("HELIX_OFFICE_FIRST", "0").lower() in {"1", "true", "yes", "on"}:
        raise RuntimeError("Full mindscape uses the standard preconscious route; disable HELIX_OFFICE_FIRST")
    return settings


def activate_native_source(package):
    """Select one native checkout, rejecting already-imported foreign modules."""
    global _ACTIVE_NATIVE_SOURCE
    package = Path(package).expanduser().resolve()
    for relative in ("context_loom/engine.py", "habitus_ai/continual_mind.py"):
        if not (package / relative).is_file():
            raise RuntimeError(f"Native source missing {package / relative}; configure mindscape.package_path or MIGHTYMEM_PATH")
    for name, loaded in tuple(sys.modules.items()):
        family = name.split(".")[0]
        if family not in {"context_loom", "habitus_ai"} or loaded is None:
            continue
        filename = getattr(loaded, "__file__", None)
        if filename is None or not Path(filename).resolve().is_relative_to(package / family):
            raise RuntimeError(f"{name} was already imported from a different package; restart with the declared composition")
    sys.path[:] = [entry for entry in sys.path if entry != str(package)]
    sys.path.insert(0, str(package))
    importlib.invalidate_caches()
    _ACTIVE_NATIVE_SOURCE = package
    return package


def selected_native_source():
    """An explicitly activated source takes precedence over saved defaults."""
    return _ACTIVE_NATIVE_SOURCE or configured_native_source()


def configured_native_source(root=ROOT):
    """Allow explicit RWKV providers to use the same source choice as main."""
    from core.model_paths import default_native_source
    root = Path(root).resolve()
    path = configuration_path(root)
    config = json.loads(path.read_text()) if path.exists() else {}
    selected = Path(config.get("mindscape", {}).get("package_path") or default_native_source(root)).expanduser()
    return (selected if selected.is_absolute() else root / selected).resolve()


def local_model_receipt(config):
    """Check the selected local service before creating state or loading weights."""
    import urllib.request
    base = config.get("ollama_url", "http://localhost:11434").rstrip("/")
    rwkv = config['local_provider'] in {'rwkv', 'bicameral_rwkv'}
    names = (os.environ.get("HELIX_SEMANTIC_MODEL", "qwen3-embedding:0.6b"),)
    if not rwkv:
        names = (config['local_model'],) + names
    elif not Path(config['local_model'], 'model.safetensors.index.json').is_file():
        raise RuntimeError('Configured foreground RWKV checkpoint is missing')
    with urllib.request.urlopen(base + "/api/tags") as response:
        available = {row["name"]: row for row in json.load(response)["models"]}
    missing = [name for name in names if name not in available]
    if missing:
        raise RuntimeError(f"Full mindscape cannot start: local models missing: {', '.join(missing)}")
    return {"url": base, "models": [available[name] for name in names],
            'foreground': {'provider': config['local_provider'], 'model': config['local_model']}}


def source_receipt(root):
    root = Path(root).resolve()
    def git(*args):
        result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
        return result.stdout.strip() if result.returncode == 0 else None
    paths = [p for directory in ("core", "memory", "llm", "tools", "brain", "comms", "dashboard", "bootstrap", "context_loom", "habitus_ai")
             for p in (root / directory).rglob("*.py")]
    paths += [p for name in ("main.py", "setup.py", "pyproject.toml") if (p := root / name).is_file()]
    return {"root": str(root), "revision": git("rev-parse", "HEAD"),
            "working_tree": git("status", "--short"),
            "files": {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}}


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, default=str, allow_nan=False) + "\n")
    temporary.replace(path)
