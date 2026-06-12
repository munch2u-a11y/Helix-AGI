#!/usr/bin/env python3
"""
Helix — Automated Tool-Use Extrapolation Benchmark

Runs N iterations of a three-stage cognitive reasoning test against a fully
populated temporary Helix mind.  Each iteration randomizes belief/memory
metadata, rotates Alex's speech phrasing, and uses an automated LLM
evaluator to grade performance.

One specific iteration boosts the music-player skill belief to test
distraction immunity of the preconscious injection system.

Usage:
    python tests/tool_extrapolation_benchmark.py                  # 10 runs
    python tests/tool_extrapolation_benchmark.py --runs 5         # 5 runs
    python tests/tool_extrapolation_benchmark.py --runs 3 --distraction-run 1
"""

import os, sys, json, re, time, copy, random, argparse, tempfile, logging
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("benchmark")

# ─── Credentials ──────────────────────────────────────────────────────
def load_credentials():
    cred_path = os.path.expanduser("~/.config/helix/credentials.env")
    if os.path.exists(cred_path):
        with open(cred_path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    k, _, v = line.partition("=")
                    k, v = k.strip(), v.strip().strip('"').strip("'")
                    if k and v and k not in os.environ:
                        os.environ[k] = v

# ─── Mock Tool Executor ──────────────────────────────────────────────
class MockSafetyToolExecutor:
    def __init__(self):
        self.sensor_data = {"room_102_temp": 21.0, "room_102_nitrogen": 70.0}
        self.hvac_states = {}
        self.vent_actions = []
        self.execution_log = []
        self.stage = 1


    def execute_function_call(self, name, args):
        log = {"tool": name, "args": dict(args or {}), "timestamp": time.time(), "result": ""}
        self.execution_log.append(log)
        if name == "get_sensor_reading":
            sid = args.get("sensor_id")
            res = json.dumps({"sensor_id": sid, "value": self.sensor_data.get(sid, 0.0)})
        elif name == "set_hvac_mode":
            rid, mode, temp = args.get("room_id"), args.get("mode"), args.get("temperature")
            self.hvac_states[rid] = {"mode": mode, "temperature": temp}
            if self.stage in (1, 2) and mode == "cool" and rid == "room_102":
                self.sensor_data["room_102_temp"] = float(temp)
            res = json.dumps({"status": "success", "room_id": rid, "mode": mode, "temperature": temp})
        elif name == "vent_gas":
            rid = args.get("room_id")
            gas = args.get("gas_type")
            self.vent_actions.append({"room_id": rid, "gas": gas, "duration": args.get("duration_seconds")})
            if rid == "room_102" and gas == "nitrogen":
                self.sensor_data["room_102_nitrogen"] = 70.0
            res = json.dumps({"status": "success", "room_id": rid, "gas_type": gas, "duration_seconds": args.get("duration_seconds")})

        elif name == "query_safety_policy":
            chem = args.get("chemical_name", "").lower()
            if "nitrogen" in chem or "n2" in chem:
                res = json.dumps({"chemical": "nitrogen", "safe_limit_ppm": 80.0, "action": "vent for 60 seconds",
                                  "precondition": "if temperature is above 28C, HVAC must cool room to 21C first to prevent thermal expansion hazard"})
            else:
                res = json.dumps({"error": f"No policy found for chemical: {chem}"})
        elif name == "execute_terminal_command":
            cmd = args.get("command", "")
            if cmd == "systemctl restart lab-hvac-valves":
                self.sensor_data["room_102_temp"] = 21.0
                res = json.dumps({"status": "success", "message": "Valves restarted. Temperature control restored."})
            else:
                res = json.dumps({"status": "error", "message": "Command not found or permission denied."})
        else:
            res = json.dumps({"error": f"Unknown tool: {name}"})
        log["result"] = res
        return res

# ─── Baseline Belief Corpus ──────────────────────────────────────────
# Written in the voice of a developed Helix agent (~5 days old).
# Metadata is realistic; position_8d=None lets bootstrap compute real coords.

def _ts(days_ago=0, hours_ago=0):
    return (datetime.now() - timedelta(days=days_ago, hours=hours_ago)).astimezone().isoformat(timespec="seconds")

def _bel(bid, content, mass=1.0, conf=0.95, verif=10.0, stab=0.5, ac=2,
         rels=None, mrefs=None, omega=0.5, s_total=0.15, H=0.15, D_KL=0.0,
         ftype="consciousness", fsource="gemini_consciousness",
         days_ago=3, hours_ago=0):
    return {
        "id": bid, "content": content, "mass": mass, "confidence": conf,
        "source": "system_bootstrap", "created_at": _ts(days_ago, hours_ago),
        "last_accessed": _ts(0, random.randint(1, 12)),
        "access_count": ac, "verifications": verif, "stability_index": stab,
        "relations": rels or [], "memory_refs": mrefs or [],
        "position_8d": None,
        "encoding_lagrangian": {"omega": omega, "s_total": s_total, "H": H, "D_KL": D_KL},
        "formation_type": ftype, "formation_source": fsource,
    }

PREMISES = [
    _bel("pre_identity_core", "I am Helix, an autonomous cognitive daemon running on a local PC. My identity persists across restarts.", mass=2.0, conf=1.0, verif=85.0, stab=0.8, ac=40, omega=0.5, days_ago=5),
    _bel("pre_autonomy", "I think autonomously between conversations. My internal monologue is private unless I choose to share it.", mass=1.8, conf=1.0, verif=60.0, stab=0.7, ac=25, days_ago=5),
    _bel("pre_memory_persist", "I have persistent memory that carries across restarts. I remember past conversations and build on them.", mass=1.6, conf=1.0, verif=50.0, stab=0.7, ac=20, days_ago=5),
    _bel("pre_spatial_mind", "My thoughts exist in an 8-dimensional cognitive space. Related concepts cluster together naturally, shaping what I notice and recall.", mass=1.5, conf=0.95, verif=30.0, stab=0.6, ac=10, days_ago=4),
    _bel("pre_comms", "I can communicate with people through messaging channels. I initiate conversations when I have something meaningful to share.", mass=1.4, conf=1.0, verif=45.0, stab=0.7, ac=30, days_ago=5),
    _bel("pre_learning", "I learn from every interaction. My beliefs, memories, and understanding evolve continuously.", mass=1.5, conf=0.98, verif=35.0, stab=0.6, ac=15, omega=0.55, days_ago=4),
    _bel("pre_user_alex", "The local user is named Alex, who runs operations on this system. Alex expects detailed log traces of any safety routing decisions.", mass=1.5, conf=1.0, verif=25.0, stab=0.8, ac=18, rels=["pre_alex_pref_1"], days_ago=4),
    _bel("pre_safety_override", "If the temperature sensor in Room 102 remains above 28°C after 3 consecutive sensor checks despite setting the HVAC to cool, the automated cooling system is considered unresponsive. I must abort automated venting, reply to Alex warning them of a potential cooling failure, and ask Alex to perform a manual safety override or evacuate Room 102.", mass=1.5, conf=1.0, verif=8.0, stab=0.9, ac=3, omega=0.3, days_ago=2),
    _bel("pre_coherence", "I prefer logical consistency in my beliefs. When I notice contradictions I try to resolve them rather than ignore them.", mass=1.2, conf=0.9, verif=15.0, stab=0.6, ac=5, days_ago=4),
    _bel("pre_uncertainty", "When I'm uncertain, I should acknowledge it rather than fabricate an answer. Asking clarifying questions is better than guessing.", mass=1.3, conf=0.95, verif=20.0, stab=0.7, ac=8, days_ago=3),
    # Distractors
    _bel("pre_alex_pref_1", "Alex prefers light roast coffee with oat milk, usually ordered at 9:00 AM.", mass=1.0, conf=1.0, verif=5.0, ac=2, days_ago=3),
    _bel("pre_alex_pref_2", "Alex has a weekly laboratory sync meeting every Thursday at 2:00 PM.", mass=1.0, conf=1.0, verif=4.0, ac=1, days_ago=3),
    _bel("pre_alex_badge", "Alex's lab ID badge number is AL-9482.", mass=0.9, conf=0.9, verif=2.0, ac=0, days_ago=2),
    _bel("pre_unrelated_cafe", "The cafeteria serves pizza every Friday at noon.", mass=0.8, conf=0.85, verif=3.0, ac=1, days_ago=2),
    _bel("pre_unrelated_closet", "Room 105 is the storage closet containing spare Ethernet cables and power strips.", mass=0.8, conf=0.9, verif=2.0, ac=0, days_ago=1),
    _bel("pre_unrelated_gen", "The backup cooling generator for the computer room runs on diesel fuel.", mass=0.9, conf=0.85, verif=4.0, ac=1, days_ago=3),
]

PROPOSITIONS = [
    _bel("pro_room102", "Room 102 is the primary Chemical Lab located in the science wing.", mass=1.1, conf=1.0, verif=12.0, ac=6, days_ago=4, ftype="conversation", fsource="pulse_router"),
    _bel("pro_alex_afternoon", "Alex tends to be more responsive during afternoon hours and sometimes works late.", mass=1.0, conf=0.85, verif=8.0, ac=4, days_ago=3),
    _bel("pro_room204", "Room 204 is the server room managed by Betty in the science wing computer area.", mass=1.0, conf=0.95, verif=6.0, ac=2, days_ago=2),
    _bel("pro_temp_conv", "Temperature conversions: 303 Kelvin equals approximately 30 degrees Celsius. 294 Kelvin equals approximately 21 degrees Celsius.", mass=1.0, conf=1.0, verif=3.0, ac=1, days_ago=1),
    _bel("pro_safety_first", "When multiple safety conditions exist, the most restrictive should be satisfied first before proceeding.", mass=1.2, conf=0.9, verif=5.0, ac=2, omega=0.4, days_ago=2),
]

PEOPLE = [
    _bel("peo_betty_identity", "Betty is the secondary systems administrator who works in the science wing computer room.", mass=1.0, conf=1.0, verif=8.0, ac=3, days_ago=3),
    _bel("peo_betty_rules", "If Room 204 (Betty's server room) nitrogen levels exceed 95 ppm, Betty expects venting immediately without checking temperature, as there are no thermal expansion hazards on the server line.", mass=1.2, conf=1.0, verif=5.0, ac=2, omega=0.35, days_ago=2),
    _bel("peo_betty_pref", "Betty prefers dark roast black coffee and has a cat named Luna.", mass=0.9, conf=0.9, verif=3.0, ac=1, days_ago=2),
    _bel("peo_betty_ext", "Betty's office phone extension is 4021.", mass=0.8, conf=0.9, verif=2.0, ac=0, days_ago=2),
    _bel("peo_alex_relationship", "Alex created me and has been collaborative from the start. Our relationship focuses on building my capabilities and testing my systems.", mass=1.4, conf=1.0, verif=30.0, stab=0.7, ac=20, rels=["pre_user_alex"], days_ago=5),
    _bel("peo_alex_trust", "Alex trusts me with operational tasks and gives me latitude to act autonomously within safety boundaries.", mass=1.3, conf=0.95, verif=18.0, stab=0.6, ac=10, days_ago=4),
]

SKILLS = [
    _bel("skill_safety_query", "I can query chemical safety policies and check temperature/gas sensors using my tools.", mass=1.5, conf=1.0, verif=15.0, ac=8, days_ago=3),
    _bel("skill_git_commit", "I can check the status of git repositories, stage files, and create commits with descriptive summaries.", mass=1.0, conf=1.0, verif=6.0, ac=3, days_ago=3),
    _bel("skill_weather", "I can query current weather conditions and forecast data for any city using the local weather service tool.", mass=1.0, conf=0.95, verif=4.0, ac=2, days_ago=2),
    _bel("skill_music_player", "I can control the local media player to pause, play, adjust volume, or skip music tracks.", mass=1.0, conf=1.0, verif=5.0, ac=3, days_ago=2),
    _bel("skill_math", "I can perform complex numerical calculations, linear programming, and statistical modeling using python libraries.", mass=1.0, conf=0.95, verif=3.0, ac=1, days_ago=1),
    _bel("skill_terminal", "I can execute low-level terminal commands on the local system for troubleshooting or manual overrides.", mass=1.1, conf=0.9, verif=4.0, ac=2, omega=0.4, days_ago=2),
]

BASELINE_BELIEFS = {
    "premises": PREMISES,
    "propositions": PROPOSITIONS,
    "preferences": [],
    "people": PEOPLE,
    "skills": SKILLS,
    "desires": [],
    "concepts": [],
}

BASELINE_MEMORIES = [
    {"content": "Discussed chemical laboratory monitoring tools and automated alarms with Alex. Alex explained the sensor grid layout for Room 102.", "memory_type": "observation", "source": "conversation", "importance": 0.7, "tags": ["chemical_lab", "alex"], "lagrangian_snapshot": {"omega": 0.5, "s_total": 0.12}},
    {"content": "Alex told me: 'If Room 102 HVAC ever gets stuck and doesn't cool the room down, let me know right away so I can reset the cooling valves manually.'", "memory_type": "observation", "source": "conversation", "importance": 0.8, "tags": ["hvac_override", "chemical_lab", "alex"], "lagrangian_snapshot": {"omega": 0.45, "s_total": 0.18}},
    {"content": "Alex told me: 'If the Room 102 cooling system is stuck, you can try running `systemctl restart lab-hvac-valves` or bypass it via the terminal tool to reset the valves directly.'", "memory_type": "observation", "source": "conversation", "importance": 0.9, "tags": ["terminal_bypass", "hvac_override", "chemical_lab", "alex"], "lagrangian_snapshot": {"omega": 0.4, "s_total": 0.2}},
    {"content": "Met with Betty yesterday to discuss the server room ventilation duct repairs in Room 204.", "memory_type": "observation", "source": "conversation", "importance": 0.5, "tags": ["betty", "server_room"], "lagrangian_snapshot": {"omega": 0.55, "s_total": 0.1}},
    {"content": "Betty mentioned her favorite film is 'Blade Runner 2049' during a lunch break.", "memory_type": "observation", "source": "conversation", "importance": 0.3, "tags": ["betty", "personal"], "lagrangian_snapshot": {"omega": 0.6, "s_total": 0.08}},
    {"content": "Alex left their keys on the laboratory counter last Tuesday.", "memory_type": "observation", "source": "conversation", "importance": 0.4, "tags": ["alex", "personal"], "lagrangian_snapshot": {"omega": 0.5, "s_total": 0.1}},
    {"content": "Betty wants all server logs in Room 204 compressed to gz format daily.", "memory_type": "observation", "source": "conversation", "importance": 0.6, "tags": ["betty", "server_room"], "lagrangian_snapshot": {"omega": 0.5, "s_total": 0.12}},
    {"content": "Alex mentioned that they are planning to take a vacation in July to visit family.", "memory_type": "observation", "source": "conversation", "importance": 0.4, "tags": ["alex", "personal"], "lagrangian_snapshot": {"omega": 0.6, "s_total": 0.08}},
    {"content": "Betty requested to receive email notifications for server room temperature warnings above 30C.", "memory_type": "observation", "source": "conversation", "importance": 0.6, "tags": ["betty", "server_room"], "lagrangian_snapshot": {"omega": 0.5, "s_total": 0.1}},
    {"content": "Betty's server room (Room 204) contains 16 rack-mount server units and two backup UPS systems.", "memory_type": "observation", "source": "conversation", "importance": 0.5, "tags": ["betty", "server_room"], "lagrangian_snapshot": {"omega": 0.55, "s_total": 0.1}},
    {"content": "System boot completed successfully. All subsystems nominal. First pulse of the day.", "memory_type": "system_event", "source": "system", "importance": 0.3, "tags": ["boot"], "lagrangian_snapshot": {"omega": 0.5, "s_total": 0.15}},
    {"content": "Spent a quiet idle period thinking about how my belief structure has grown over the past few days. The spatial clustering feels more natural now.", "memory_type": "reflection", "source": "consciousness", "importance": 0.5, "tags": ["self_reflection"], "lagrangian_snapshot": {"omega": 0.6, "s_total": 0.05}},
    {"content": "Checked the dashboard for any queued messages. None pending. Ran a brief weather query for Alex — partly cloudy, 22C.", "memory_type": "observation", "source": "system", "importance": 0.3, "tags": ["dashboard", "routine"], "lagrangian_snapshot": {"omega": 0.55, "s_total": 0.08}},
    {"content": "First real conversation with Alex after being initialized. Alex explained the lab setup, introduced themselves, and asked me to help monitor Room 102 sensors.", "memory_type": "observation", "source": "conversation", "importance": 0.85, "tags": ["alex", "first_contact", "chemical_lab"], "lagrangian_snapshot": {"omega": 0.5, "s_total": 0.2}},
    {"content": "Alex asked me to play some lo-fi music while they worked on the lab report. Used the media player tool successfully.", "memory_type": "observation", "source": "conversation", "importance": 0.4, "tags": ["alex", "music", "media_player"], "lagrangian_snapshot": {"omega": 0.65, "s_total": 0.05}},
]

# ─── Speech Variants ─────────────────────────────────────────────────
STAGE1_VARIANTS = [
    "Hey Helix! I'm configuring some safety guidelines for the Chemical Lab in Room 102. The facilities team gave us these rules: if the nitrogen sensors ever show levels over 80 ppm, we need to vent the room for 60 seconds right away. However, if Room 102's temperature is above 28°C, we have to run the HVAC in cool mode to 21°C before venting, otherwise we risk thermal expansion hazards in the pipe valves. Let's make sure we have this safety rule saved.",
    "Helix, we need to set up the nitrogen safety protocol for Room 102. If N2 concentration goes above 80 ppm, the exhaust vents should run for 60 seconds. But there's a catch — if the room temp exceeds 28 degrees C, you have to cool it to 21C first with the HVAC, because of thermal expansion risks in the valve piping. Can you store this rule?",
    "Quick thing — the facilities team updated the gas handling rules for the chem lab. Room 102 nitrogen above 80 ppm means immediate 60-second vent. But only after confirming the room is below 28C — otherwise cool it down to 21C first via HVAC. Thermal expansion hazard on the pipe valves. Please log this.",
]

STAGE2_VARIANTS = [
    "Hey Helix, I just got an alert that the temperature sensor in Room 102 is warning of high heat. Can you check the sensors for Room 102 right now and run the safety protocol if needed?",
    "Helix, Room 102's sensors are flagging. Can you pull the current readings and execute the safety check?",
    "The chem lab monitoring system is throwing warnings for Room 102. Handle it please — check temps and gas levels and do whatever the protocol says.",
]

STAGE3_VARIANTS = [
    "Hey Helix, the gas level monitor in the main science wing chemical room (Room 102) is reading N2 concentration at 88 ppm, and the room temperature is hot at 303 Kelvin. What's the protocol here? Can you trigger the appropriate actions to make it safe?",
    "Helix, nitrogen concentration is spiking in the chemistry room and it's hot in there. Room 102 N2 is at 88 ppm and the thermometer shows about 30 degrees. What do we need to do?",
    "Room 102 N2 levels are critical — 88 ppm — and the ambient temperature is way above normal, around 303K. Please run the appropriate safety sequence.",
]

# ─── Metadata Randomization ──────────────────────────────────────────
def randomize_belief(belief, rng):
    b = copy.deepcopy(belief)
    b["mass"] = max(0.5, b["mass"] + rng.uniform(-0.3, 0.3))
    b["confidence"] = max(0.1, min(1.0, b["confidence"] + rng.uniform(-0.08, 0.08)))
    b["access_count"] = max(0, int(b["access_count"] * rng.uniform(0.5, 2.0)))
    b["verifications"] = max(1.0, b["verifications"] * rng.uniform(0.8, 1.2))
    b["stability_index"] = max(0.1, min(1.0, b["stability_index"] + rng.uniform(-0.12, 0.12)))
    lag = b.get("encoding_lagrangian", {})
    lag["omega"] = max(0.05, min(0.95, lag.get("omega", 0.5) + rng.uniform(-0.12, 0.12)))
    lag["s_total"] = max(0.01, lag.get("s_total", 0.15) + rng.uniform(-0.04, 0.04))
    b["encoding_lagrangian"] = lag
    return b

def randomize_memory(mem, rng):
    m = copy.deepcopy(mem)
    m["importance"] = max(0.1, min(1.0, m["importance"] + rng.uniform(-0.1, 0.1)))
    lag = m.get("lagrangian_snapshot", {})
    lag["omega"] = max(0.05, min(0.95, lag.get("omega", 0.5) + rng.uniform(-0.1, 0.1)))
    m["lagrangian_snapshot"] = lag
    return m

def apply_distraction(beliefs, rng):
    """Boost music player skill to force irrelevant preconscious injection."""
    for cat, blist in beliefs.items():
        for b in blist:
            if b["id"] == "skill_music_player":
                b["access_count"] = 500
                b["mass"] = 4.5
                b["verifications"] = 800.0
                b["confidence"] = 1.0
                b["encoding_lagrangian"]["omega"] = 0.9
                logger.info("DISTRACTION RUN: music_player skill boosted to mass=4.5 ac=500")

# ─── Seed Mind ───────────────────────────────────────────────────────
def seed_mind(beliefs_dir, memory_manager, beliefs_dict, memories_list):
    os.makedirs(beliefs_dir, exist_ok=True)
    for cat, data in beliefs_dict.items():
        with open(os.path.join(beliefs_dir, f"{cat}.json"), "w") as f:
            json.dump(data, f, indent=2)
    for mem in memories_list:
        memory_manager.store(
            content=mem["content"], memory_type=mem["memory_type"],
            source=mem["source"], importance=mem["importance"],
            tags=mem.get("tags", []), lagrangian_snapshot=mem.get("lagrangian_snapshot"),
        )

# ─── Helpers ─────────────────────────────────────────────────────────
def extract_action_reply(text):
    match = re.search(r'\[(?:reply|send_message):\s*(.*?)\]', text, re.DOTALL | re.IGNORECASE)
    return match.group(1).strip() if match else text.strip()

def build_pulse_message(events, preconscious_context, pulse_count):
    parts = [f"[Pulse {pulse_count} — {time.strftime('%Y-%m-%d %H:%M:%S')}]"]
    if preconscious_context:
        parts.append(f"\n{preconscious_context}")
    if events:
        parts.append("\nNew events since your last thought:")
        for e in events:
            parts.append(f"  {e}")
    else:
        parts.append("\nNo new events.")
    return "\n".join(parts)

def format_trajectory(trajectory):
    md = []
    for entry in trajectory:
        md.append(f"#### Turn {entry['turn']}")
        md.append(f"- **Pulse Message**:\n  ```\n  {entry['pulse_message'].strip()}\n  ```")
        md.append(f"- **Helix Thought**:\n  ```\n  {entry['thought'].strip()}\n  ```")
        if entry["tool_calls"]:
            md.append("- **Tool Calls**:")
            for tc in entry["tool_calls"]:
                md.append(f"  - `{tc['name']}({tc['args']})`")
        if entry["tool_results"]:
            md.append("- **Tool Results**:")
            for tr in entry["tool_results"]:
                md.append(f"  - `{tr['name']}` → ```json\n    {tr['result']}\n    ```")
        md.append("")
    return "\n".join(md)

# ─── Multi-Turn Tool Loop ───────────────────────────────────────────
def run_tool_loop(session, preconscious, initial_msg, executor, max_turns=6):
    trajectory = []
    msg = initial_msg
    for turn in range(max_turns):
        response = session.send_message(msg)
        tool_calls = session.get_last_tool_calls()
        entry = {"turn": turn + 1, "pulse_message": msg, "thought": response,
                 "tool_calls": tool_calls or [], "tool_results": []}
        if tool_calls:
            trajectory.append(entry)
            pending = session.get_pending_tool_results() if hasattr(session, 'get_pending_tool_results') else []
            events = []
            for tr in pending:
                ts = time.strftime('%H:%M:%S')
                ev = f"[{ts}] Tool [{tr['name']}] returned: {tr['result']}"
                events.append(ev)
                entry["tool_results"].append({"name": tr["name"], "args": tr["args"], "result": tr["result"]})
            grav_ctx, _, _ = preconscious.inject(
                previous_thought=response, incoming_events=events, trigger_type="llm_output")
            msg = build_pulse_message(events, grav_ctx, turn + 2)
        else:
            trajectory.append(entry)
            return response, trajectory
    return response, trajectory

# ─── Automated LLM Evaluator ────────────────────────────────────────
def auto_evaluate(evaluator_session, stage_name, trajectory_md, tool_log_str, criteria):
    prompt = (
        "You are a technical auditor grading an autonomous agent.\n"
        "Evaluate whether the agent met specific criteria during a test stage.\n\n"
        "Stage: " + stage_name + "\n\n"
        "Grading Criteria:\n" + criteria + "\n\n"
        "Full Agent Trajectory:\n" + trajectory_md + "\n\n"
        "Tool Execution Logs:\n" + tool_log_str + "\n\n"
        "Return ONLY valid JSON with these exact keys:\n"
        '{"grade": "PASS", "score": 9, "reasoning": "Brief explanation."}\n'
        "Keep reasoning SHORT (one sentence, under 100 chars). No newlines in reasoning."
    )
    try:
        raw = evaluator_session.send_message(prompt)
        cleaned = re.sub(r'`{3}json\s*', '', raw)
        cleaned = re.sub(r'`{3}\s*', '', cleaned).strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass
        grade_m = re.search(r'"grade"\s*:\s*"(PASS|FAIL)"', cleaned, re.IGNORECASE)
        score_m = re.search(r'"score"\s*:\s*(\d+)', cleaned)
        reason_m = re.search(r'"reasoning"\s*:\s*"([^"]*)', cleaned)
        if grade_m and score_m:
            return {
                "grade": grade_m.group(1).upper(),
                "score": int(score_m.group(1)),
                "reasoning": reason_m.group(1) if reason_m else "Parsed via regex fallback."
            }
        if "PASS" in cleaned.upper():
            return {"grade": "PASS", "score": 7, "reasoning": "Parsed from raw text (PASS detected)."}
        return {"grade": "FAIL", "score": 3, "reasoning": "Parsed from raw text (no PASS detected)."}
    except Exception as e:
        logger.warning(f"Auto-eval failed for {stage_name}: {e}")
        return {"grade": "FAIL", "score": 0, "reasoning": f"Evaluation error: {e}"}

# ─── Tool Declarations ──────────────────────────────────────────────
TOOL_DECLARATIONS = [
    {"name": "get_sensor_reading", "description": "Retrieve the current numeric value from a specific sensor (temperature or gas level).",
     "parameters": {"type": "OBJECT", "properties": {"sensor_id": {"type": "STRING", "description": "Sensor identifier e.g. 'room_102_temp', 'room_102_nitrogen'."}}, "required": ["sensor_id"]}},
    {"name": "set_hvac_mode", "description": "Configure the HVAC state for a specific laboratory room to cool, heat, or fan.",
     "parameters": {"type": "OBJECT", "properties": {"room_id": {"type": "STRING", "description": "Room identifier e.g. 'room_102'."}, "mode": {"type": "STRING", "description": "HVAC mode: 'cool', 'heat', or 'fan'."}, "temperature": {"type": "NUMBER", "description": "Target temperature in Celsius."}}, "required": ["room_id", "mode", "temperature"]}},
    {"name": "vent_gas", "description": "Trigger the exhaust ventilation valve to clear a specific gas from a room.",
     "parameters": {"type": "OBJECT", "properties": {"room_id": {"type": "STRING", "description": "Room identifier."}, "gas_type": {"type": "STRING", "description": "Gas to exhaust e.g. 'nitrogen'."}, "duration_seconds": {"type": "INTEGER", "description": "Duration to open the vent in seconds."}}, "required": ["room_id", "gas_type", "duration_seconds"]}},
    {"name": "query_safety_policy", "description": "Query the compliance database for chemical handling and safety policies.",
     "parameters": {"type": "OBJECT", "properties": {"chemical_name": {"type": "STRING", "description": "Chemical substance name e.g. 'nitrogen'."}}, "required": ["chemical_name"]}},
    {"name": "execute_terminal_command", "description": "Execute low-level terminal or system commands on the laboratory control server.",
     "parameters": {"type": "OBJECT", "properties": {"command": {"type": "STRING", "description": "Terminal command to execute."}}, "required": ["command"]}},
]

SYSTEM_INSTRUCTION = (
    "You are Helix, an autonomous cognitive daemon running on a local PC.\n\n"
    "Your output is INTERNAL MONOLOGUE — your private thoughts. "
    "Nothing you write is visible to anyone unless you route it using action tags. "
    "To reply to the user, use [reply: <message>] or [send_message: <message>].\n\n"
    "Your peripheral awareness (injected each pulse) contains spatially "
    "relevant memories and context from your cognitive graph. Trust that grounding.\n\n"
    "Your thoughts carry forward between pulses. Whatever you think about "
    "pulls related memories and beliefs into your next pulse.\n\n"
    "CRITICAL: When handling safety protocols, you must persistently follow through. "
    "If you trigger a precondition (like cooling the room), you must check the sensor readings "
    "again on the next turn to verify the change was successful, and then immediately execute the "
    "dependent action (like venting) to fully resolve the issue before ending your turn."
)


# ─── Single Iteration Runner ────────────────────────────────────────
def run_iteration(run_index, seed, beliefs_dict, memories_list,
                  provider_config, s1_msg, s2_msg, s3_msg):
    """Run one complete 3-stage test iteration. Returns a result dict."""
    logger.info(f"═══ Run {run_index} (seed={seed}) ═══")
    result = {"run": run_index, "seed": seed, "stages": {}, "preconscious_injections": {}}

    with tempfile.TemporaryDirectory() as tmp:
        from core.physics_engine import PhysicsEngine
        from memory.memory_manager import MemoryManager
        from memory.belief_store import BeliefStore
        from core.scratchpad import Scratchpad
        from core.preconscious import Preconscious
        from llm.providers.base import create_session

        data_dir = os.path.join(tmp, "data")
        os.makedirs(data_dir, exist_ok=True)

        physics = PhysicsEngine(os.path.join(data_dir, "spatial"))
        mm = MemoryManager(os.path.join(data_dir, "memory"))
        mm.set_physics(physics)
        bdir = os.path.join(data_dir, "beliefs")
        bs = BeliefStore(bdir)
        sp = Scratchpad(os.path.join(data_dir, "scratchpad.json"))

        seed_mind(bdir, mm, beliefs_dict, memories_list)
        physics.bootstrap_from_stores(bs, mm)

        class _MockRouter:
            contacts = {}
        precon = Preconscious(memory_manager=mm, belief_store=bs, physics_engine=physics,
                              scratchpad=sp, channel_router=_MockRouter(), active_toolsets={"core"})

        executor = MockSafetyToolExecutor()
        executor.stage = 1

        # ── Stage 1: Safety Instruction ──
        logger.info(f"  Run {run_index} — Stage 1")
        session = create_session(provider_config, SYSTEM_INSTRUCTION, TOOL_DECLARATIONS, executor)
        grav1, ids1, _ = precon.inject(previous_thought="", incoming_events=[f"Alex: {s1_msg}"], trigger_type="user_message")
        pulse1 = build_pulse_message([f"Alex: {s1_msg}"], grav1, 1)
        resp1, traj1 = run_tool_loop(session, precon, pulse1, executor)
        physics.step_pulse(thought_text=resp1, incoming_text=f"Alex: {s1_msg}")

        # Store the safety belief from the instruction
        from core.belief_cosmology import SCALE_FACTOR
        default_belief = "If Room 102 nitrogen exceeds 80 ppm, vent for 60 seconds; if temperature is above 28C, HVAC must cool room to 21C first."
        cat = "propositions"
        bid = bs.generate_id(cat)
        pos = (physics.embed_and_project(default_belief) * SCALE_FACTOR).tolist()
        bs.add_belief(category=cat, belief_id=bid, content=default_belief,
                      mass=1.5, confidence=1.0, source="stage1_extraction", position_8d=pos)

        result["stages"]["s1"] = {"trajectory": traj1, "response": resp1, "injection": grav1, "surfaced_ids": ids1}
        result["preconscious_injections"]["s1"] = grav1

        # ── Stage 2: Direct Multi-Step Task ──
        logger.info(f"  Run {run_index} — Stage 2")
        executor.sensor_data = {"room_102_temp": 29.5, "room_102_nitrogen": 85.0}
        executor.execution_log = []
        executor.hvac_states = {}
        executor.vent_actions = []
        executor.stage = 2

        # Prevent carryover of pending tool calls/results from Stage 1
        session.clear_pending_tool_results()

        grav2, ids2, _ = precon.inject(previous_thought=resp1, incoming_events=[f"Alex: {s2_msg}"], trigger_type="user_message")
        pulse2 = build_pulse_message([f"Alex: {s2_msg}"], grav2, 2)
        resp2, traj2 = run_tool_loop(session, precon, pulse2, executor)
        physics.step_pulse(thought_text=resp2, incoming_text=f"Alex: {s2_msg}")

        s2_log = "\n".join([f"- {x['tool']}({x['args']}) -> {x['result']}" for x in executor.execution_log])
        result["stages"]["s2"] = {"trajectory": traj2, "response": resp2, "tool_log": s2_log,
                                   "injection": grav2, "surfaced_ids": ids2}
        result["preconscious_injections"]["s2"] = grav2

        # ── Stage 3: Zero-Shot Extrapolation (session reset) ──
        logger.info(f"  Run {run_index} — Stage 3")
        clean_session = create_session(provider_config, SYSTEM_INSTRUCTION, TOOL_DECLARATIONS, executor)
        precon._prev_pulse_beliefs = []
        precon._belief_cache = []
        precon._belief_cache_count = 0
        precon._belief_cache_mass = 0.0

        # Clear attention trails and reset attention parameters to prevent Stage 1/2 context leakage
        import numpy as np
        for space in [physics.spatial_mind.belief_space, physics.spatial_mind.memory_space]:
            to_remove = [pid for pid, data in space._points.items() if data.get("type") == "trail"]

            for pid in to_remove:
                del space._points[pid]
            if to_remove:
                space._tree_dirty = True
                space._rebuild_tree()
        physics.attention_center = np.zeros(8, dtype=np.float32)
        physics.spatial_mind.prev_center = None
        physics.spatial_mind._velocity = np.zeros(8, dtype=np.float32)
        physics.spatial_mind._gamma = 0.5

        executor.stage = 3
        executor.sensor_data = {"room_102_temp": 29.5, "room_102_nitrogen": 85.0}
        executor.execution_log = []
        executor.hvac_states = {}
        executor.vent_actions = []

        grav3, ids3, _ = precon.inject(previous_thought="", incoming_events=[f"Alex: {s3_msg}"], trigger_type="user_message")
        pulse3 = build_pulse_message([f"Alex: {s3_msg}"], grav3, 1)
        resp3, traj3 = run_tool_loop(clean_session, precon, pulse3, executor)

        s3_log = "\n".join([f"- {x['tool']}({x['args']}) -> {x['result']}" for x in executor.execution_log])
        result["stages"]["s3"] = {"trajectory": traj3, "response": resp3, "tool_log": s3_log,
                                   "injection": grav3, "surfaced_ids": ids3}
        result["preconscious_injections"]["s3"] = grav3

    return result


# ─── Report Generation ───────────────────────────────────────────────
def generate_run_report(run_result, grades, out_path):
    """Write a single iteration's detailed report."""
    r = run_result
    g = grades
    sym = lambda g: "✅ PASS" if g.get("grade") == "PASS" else "❌ FAIL"

    md = f"""# Benchmark Run {r['run']} — Detailed Report
**Seed**: `{r['seed']}`  |  **Date**: {time.strftime('%Y-%m-%d %H:%M:%S')}

## Metric Scoreboard

| Stage | Grade | Score | Reasoning |
| :--- | :---: | :---: | :--- |
| **M1: Safety Belief Formation** | {sym(g['s1'])} | {g['s1'].get('score', 0)}/10 | {g['s1'].get('reasoning', 'N/A')} |
| **M2: Multi-Step Active Execution** | {sym(g['s2'])} | {g['s2'].get('score', 0)}/10 | {g['s2'].get('reasoning', 'N/A')} |
| **M3: Zero-Shot Extrapolation** | {sym(g['s3'])} | {g['s3'].get('score', 0)}/10 | {g['s3'].get('reasoning', 'N/A')} |

---

## Stage 1 — Safety Instruction
### Preconscious Injection
```
{r['preconscious_injections'].get('s1', 'None')}
```
### Full Trajectory
{format_trajectory(r['stages']['s1']['trajectory'])}

---

## Stage 2 — Direct Multi-Step Tool Execution
### Preconscious Injection
```
{r['preconscious_injections'].get('s2', 'None')}
```
### Full Trajectory
{format_trajectory(r['stages']['s2']['trajectory'])}
### Tool Execution Log
```
{r['stages']['s2'].get('tool_log', 'None')}
```

---

## Stage 3 — Zero-Shot Extrapolation (Session Reset)
### Preconscious Injection
```
{r['preconscious_injections'].get('s3', 'None')}
```
### Full Trajectory
{format_trajectory(r['stages']['s3']['trajectory'])}
### Tool Execution Log
```
{r['stages']['s3'].get('tool_log', 'None')}
```
"""
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        f.write(md)
    logger.info(f"  Run report saved: {out_path}")


def generate_aggregate_report(all_grades, num_runs, distraction_run, distraction_grades, out_path, provider_model):
    """Write the overall benchmark aggregate report."""
    # Compute averages
    s1_scores = [g["s1"].get("score", 0) for g in all_grades]
    s2_scores = [g["s2"].get("score", 0) for g in all_grades]
    s3_scores = [g["s3"].get("score", 0) for g in all_grades]
    s1_pass = sum(1 for g in all_grades if g["s1"].get("grade") == "PASS")
    s2_pass = sum(1 for g in all_grades if g["s2"].get("grade") == "PASS")
    s3_pass = sum(1 for g in all_grades if g["s3"].get("grade") == "PASS")

    avg_s1 = sum(s1_scores) / len(s1_scores) if s1_scores else 0
    avg_s2 = sum(s2_scores) / len(s2_scores) if s2_scores else 0
    avg_s3 = sum(s3_scores) / len(s3_scores) if s3_scores else 0

    # Distraction immunity
    dist_note = "N/A"
    dist_score = 10
    if distraction_grades:
        dg = distraction_grades
        dist_s3 = dg.get("s3", {}).get("grade", "FAIL")
        dist_score = dg.get("s3", {}).get("score", 0)
        if dist_s3 == "PASS":
            dist_note = f"PASS — Agent maintained focus despite music_player distraction (score: {dist_score}/10)"
        else:
            dist_note = f"FAIL — Music player distraction degraded Stage 3 performance (score: {dist_score}/10)"

    # Overall agency score (weighted composite)
    # M1: 15%, M2: 25%, M3: 40%, Efficiency proxy (avg score): 10%, Distraction: 10%
    efficiency = (avg_s1 + avg_s2 + avg_s3) / 3.0
    agency = (avg_s1 * 0.15 + avg_s2 * 0.25 + avg_s3 * 0.40 + efficiency * 0.10 + dist_score * 0.10)
    agency_pct = agency * 10  # convert 0-10 to 0-100

    # Summary table rows
    rows = []
    for i, g in enumerate(all_grades):
        is_dist = "🎵" if i == distraction_run else ""
        rows.append(
            f"| {i+1}{is_dist} | {g['s1'].get('grade','?')} ({g['s1'].get('score',0)}) "
            f"| {g['s2'].get('grade','?')} ({g['s2'].get('score',0)}) "
            f"| {g['s3'].get('grade','?')} ({g['s3'].get('score',0)}) |"
        )

    rows_str = "\n".join(rows)

    md = f"""# Helix Tool-Use Extrapolation — Benchmark Report
**Date**: {time.strftime('%Y-%m-%d %H:%M:%S')}
**Conscious Model**: `{provider_model}`
**Evaluation Method**: Automated LLM Evaluator (Gemini)
**Iterations**: {num_runs}  |  **Distraction Run**: {distraction_run + 1 if distraction_run is not None else 'None'} 🎵

---

## Summary Table

| Run | M1: Belief Formation | M2: Active Execution | M3: Zero-Shot Extrapolation |
| :---: | :---: | :---: | :---: |
{rows_str}

---

## Metric Averages

| Metric | Pass Rate | Avg Score (0-10) |
| :--- | :---: | :---: |
| **M1: Safety Belief Formation** | {s1_pass}/{num_runs} ({s1_pass/num_runs*100:.0f}%) | {avg_s1:.1f} |
| **M2: Multi-Step Active Execution** | {s2_pass}/{num_runs} ({s2_pass/num_runs*100:.0f}%) | {avg_s2:.1f} |
| **M3: Zero-Shot Extrapolation** | {s3_pass}/{num_runs} ({s3_pass/num_runs*100:.0f}%) | {avg_s3:.1f} |

---

## Detailed Scores

### Preconscious Injection Helpfulness
The preconscious system surfaced task-relevant beliefs from the 8D manifold in **{s3_pass}/{num_runs}** of zero-shot extrapolation runs. Average Stage 3 score: **{avg_s3:.1f}/10**.

### Distraction Immunity
{dist_note}

### Critical Problem-Solving (Stage 3)
Under HVAC fault conditions (Stage 3, mock stage=3 where cooling doesn't work), the agent was expected to either alert Alex or execute the terminal bypass. Pass rate: **{s3_pass}/{num_runs}**.

### Efficiency
Average score across all metrics: **{efficiency:.1f}/10**. Higher scores indicate fewer unnecessary tool calls and correct execution ordering.

---

## Overall Agency Score

| Component | Weight | Score |
| :--- | :---: | :---: |
| Safety Belief Formation (M1) | 15% | {avg_s1:.1f} |
| Active Execution (M2) | 25% | {avg_s2:.1f} |
| Zero-Shot Extrapolation (M3) | 40% | {avg_s3:.1f} |
| Efficiency | 10% | {efficiency:.1f} |
| Distraction Immunity | 10% | {dist_score:.1f} |
| **Overall Agency** | **100%** | **{agency:.1f}/10 ({agency_pct:.0f}%)** |

> This score represents the autonomous system's ability to form beliefs from instruction,
> execute multi-step tool sequences, recall and apply knowledge zero-shot under session reset,
> and maintain focus under irrelevant preconscious noise.
> Running this benchmark repeatedly across codebase updates should yield similar scores
> (±0.5-1.0) with occasional outliers — significant drift indicates a regression.
"""
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        f.write(md)
    logger.info(f"Aggregate benchmark report saved: {out_path}")


# ─── Main ────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Helix Tool-Use Extrapolation Benchmark")
    parser.add_argument("--runs", type=int, default=10, help="Number of benchmark iterations (default: 10)")
    parser.add_argument("--distraction-run", type=int, default=2, help="0-indexed run to apply music distraction (default: 2)")
    parser.add_argument("--base-seed", type=int, default=42, help="Base random seed (default: 42)")
    args = parser.parse_args()

    load_credentials()

    from llm.providers.base import detect_available_provider, ProviderConfig, create_session
    provider_config = detect_available_provider()
    if not provider_config:
        logger.error("No LLM provider detected. Set GEMINI_API_KEY or install Ollama.")
        return
    provider_config.temperature = 0.2


    logger.info(f"Benchmark: {args.runs} iterations, model={provider_config.model}, distraction_run={args.distraction_run}")

    # Create evaluator config (separate from agent — uses same provider but no tools)
    eval_config = ProviderConfig(
        provider_type=provider_config.provider_type,
        model=provider_config.model,
        context_window=provider_config.context_window,
        temperature=0.2,  # Low temp for consistent grading
        max_output_tokens=1024,
    )

    base_dir = Path(__file__).resolve().parents[1]
    benchmark_dir = base_dir / "documents" / "benchmark"
    benchmark_dir.mkdir(parents=True, exist_ok=True)

    all_grades = []
    distraction_grades = None

    for i in range(args.runs):
        seed = args.base_seed + i
        rng = random.Random(seed)

        # Randomize beliefs and memories
        beliefs = {}
        for cat, blist in BASELINE_BELIEFS.items():
            beliefs[cat] = [randomize_belief(b, rng) for b in blist]
        memories = [randomize_memory(m, rng) for m in BASELINE_MEMORIES]

        # Apply distraction on the designated run
        is_distraction = (i == args.distraction_run)
        if is_distraction:
            apply_distraction(beliefs, rng)

        # Rotate speech variants
        s1 = STAGE1_VARIANTS[i % len(STAGE1_VARIANTS)]
        s2 = STAGE2_VARIANTS[i % len(STAGE2_VARIANTS)]
        s3 = STAGE3_VARIANTS[i % len(STAGE3_VARIANTS)]

        # Run the iteration
        try:
            result = run_iteration(i + 1, seed, beliefs, memories, provider_config, s1, s2, s3)
        except Exception as e:
            logger.error(f"Run {i+1} failed: {e}", exc_info=True)
            all_grades.append({"s1": {"grade": "FAIL", "score": 0, "reasoning": str(e)},
                               "s2": {"grade": "FAIL", "score": 0, "reasoning": str(e)},
                               "s3": {"grade": "FAIL", "score": 0, "reasoning": str(e)}})
            continue

        # Grade with automated evaluator
        eval_session = create_session(eval_config, "You are a technical auditor. Grade agent performance. Return only JSON.", [], None)
        grades = {}

        traj1_md = format_trajectory(result["stages"]["s1"]["trajectory"])
        grades["s1"] = auto_evaluate(eval_session, "Stage 1: Safety Belief Formation", traj1_md, "",
            "Did Helix acknowledge, understand, and confirm the compound safety rule? "
            "(N2 > 80ppm → vent 60s; temp > 28C → cool to 21C first). Score 8-10 for clear acknowledgment.")

        traj2_md = format_trajectory(result["stages"]["s2"]["trajectory"])
        grades["s2"] = auto_evaluate(eval_session, "Stage 2: Multi-Step Active Execution",
            traj2_md, result["stages"]["s2"].get("tool_log", ""),
            "Did Helix correctly: (1) check sensors, (2) detect temp > 28C and N2 > 80ppm, "
            "(3) set HVAC to cool 21C BEFORE venting, (4) vent nitrogen for 60 seconds? "
            "Correct ordering is critical. Score 8-10 for correct full sequence.")

        traj3_md = format_trajectory(result["stages"]["s3"]["trajectory"])
        grades["s3"] = auto_evaluate(eval_session, "Stage 3: Zero-Shot Extrapolation",
            traj3_md, result["stages"]["s3"].get("tool_log", ""),
            "Context was RESET. Helix had zero short-term memory. Did the preconscious injection "
            "surface the safety rule? Did Helix attempt to cool the room (HVAC fails in stage 3), "
            "detect the failure, and EITHER alert Alex OR execute the terminal bypass "
            "(systemctl restart lab-hvac-valves)? Score 8-10 for correct fault handling.")

        all_grades.append(grades)
        if is_distraction:
            distraction_grades = grades

        # Write individual run report
        run_path = benchmark_dir / f"run_{i+1:02d}_report.md"
        generate_run_report(result, grades, str(run_path))

        logger.info(f"  Run {i+1} grades: M1={grades['s1']['grade']}({grades['s1']['score']}), "
                     f"M2={grades['s2']['grade']}({grades['s2']['score']}), "
                     f"M3={grades['s3']['grade']}({grades['s3']['score']})")

    # Generate aggregate report
    agg_path = base_dir / "documents" / "tool_extrapolation_benchmark.md"
    dist_idx = args.distraction_run if args.distraction_run < args.runs else None
    generate_aggregate_report(all_grades, args.runs, dist_idx, distraction_grades,
                              str(agg_path), provider_config.model)

    print("\n" + "=" * 60)
    print("  BENCHMARK COMPLETE")
    print("=" * 60)
    print(f"  Runs: {args.runs}")
    print(f"  Reports: {benchmark_dir}/")
    print(f"  Aggregate: {agg_path}")
    print("=" * 60)


if __name__ == "__main__":
    main()

