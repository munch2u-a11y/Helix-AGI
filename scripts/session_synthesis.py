import re
import os

def synthesize_session(log_path, lines=300):
    if not os.path.exists(log_path):
        print(f"Log file not found: {log_path}")
        return

    with open(log_path, 'r') as f:
        log_lines = f.readlines()[-lines:]

    print(f"--- Session Synthesis (Last {lines} lines) ---")
    
    for line in log_lines:
        # Tool Calls (Inbound to the system from the model)
        if "INFO: FC[" in line:
            match = re.search(r'FC\[\d+\]: (\w+)\((.*)\)', line)
            if match:
                tool_name = match.group(1)
                args = match.group(2)
                # Filter out the synthesis script itself to avoid noise
                if "session_synthesis.py" not in args:
                    print(f"[TOOL] {tool_name}: {args[:100]}...")
        
        # Tool Results (Briefly)
        if "INFO: FC[" in line and "result (" in line:
            match = re.search(r'result \((\w+)\): (.*)', line)
            if match:
                tool_name = match.group(1)
                result = match.group(2)
                if "session_synthesis.py" not in result:
                    print(f"  [RES] {tool_name}: {result[:80]}...")

        # Outbound Comms (using the router for clean names)
        if "[helix.tools.channel_router] INFO: Telegram →" in line:
            msg = line.split("): ", 1)[-1].strip()
            name_match = re.search(r'Telegram → (\w+)', line)
            name = name_match.group(1) if name_match else "Unknown"
            print(f"[OUT] Telegram to {name}: {msg[:100]}...")
        
        # Inbound Comms
        if "[helix.comms.telegram] INFO: Telegram from" in line:
            msg = line.split(": ", 1)[-1].strip()
            name_match = re.search(r'Telegram from (\w+)', line)
            name = name_match.group(1) if name_match else "Unknown"
            print(f"[IN]  Telegram from {name}: {msg[:100]}...")

if __name__ == "__main__":
    # Absolute path for reliability within the pulse environment
    log_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs", "helix.log")
    synthesize_session(log_file)
