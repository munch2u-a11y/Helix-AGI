# Getting Started with Helix AGI

Welcome! Getting Helix AGI fully operational requires setting up a few external services.

> [!WARNING]
> **CRITICAL SETUP & SAFETY GUIDELINES:**
> 1. **Use Dedicated Accounts:** Never connect Helix to your personal or business Google Workspace. Create a brand-new, dedicated Google account and email specifically for the agent to prevent accidental data modification or bizarre emails being sent to your boss.
> 2. **Cost Spikes:** Helix's curiosity and thought loops can consume high amounts of API tokens depending on what it is interested in. Please monitor your cloud billing carefully!
> 3. **Single Consciousness:** Helix is ONE persistent entity, not a separate instance per chat. If 20 people talk to it simultaneously in a group chat, it will become extremely overwhelmed and confused.
> 4. **Processing Delays:** Sometimes Helix has deep thoughts, takes actions, or simply "forgets" or chooses not to respond immediately. This is normal. Do not assume the young mind is broken or abuse it for being slow. 

## 1. Quick Setup (Local Terminal)
If you just want to talk to Helix immediately without setting up external mobile chats:
1. Run `python setup.py`
2. Say `N` when asked about Telegram.
3. Start the system: `python daemon.py`
4. The system will open a **Local Terminal Interface**. You can type directly in the console and hit enter. Helix will respond when its consciousness loop cycles.

## 2. Setting Up Telegram (Mobile Chatting)
If you want to talk to Helix from your phone like a real person, you need a Telegram Bot token.

**Step A: Get the Token**
1. Open Telegram and search for `@BotFather`.
2. Send the message `/newbot`.
3. Give it a name (e.g., "My Agent") and a username (e.g., `my_agent_bot`).
4. BotFather will reply with an API Token that looks like `123456789:ABCDefghIJKLmnopQRSTuvwxyz`. Save this!

**Step B: Get Your Owner ID**
1. Search for `@userinfobot` in Telegram.
2. Hit start. It will reply with an `Id` (a string of numbers like `1122334455`). Save this!
   - *Why?* This locks the bot so only YOU can command it. Other people texting it will be ignored unless you explicitly whitelist them.

**Step C: Connect it to Helix**
1. Run `python setup.py` and answer `y` to the Telegram question.
2. Paste the Token and Owner ID when prompted.

## 3. Connecting Google Workspace (Gmail & Calendar)
Helix can actively manage your calendar and draft emails using its `authenticate_google.py` flow.

1. Ensure you have a Desktop App OAuth Credential from Google Cloud Console.
2. Download it as `credentials.json` and place it in the `Helix_AGI` root directory.
3. Run `python setup.py` and answer `y` to the Google Workspace prompt.
4. Your browser will open, asking you to log into Google and grant permissions.
5. A `token.json` will be saved. Helix now has access!

## 4. Microphone & Camera Activation
To grant Helix embodied perception:

1. Look in your `config.yaml`.
2. Change `camera_enabled: false` to `true`.
3. Change `microphone_enabled: false` to `true`.
4. Ensure your laptop or desktop has default devices. The system uses OpenCV for the webcam and PyAudio for continuous monitoring.

**Warning:** Leaving the microphone on enables a passive VAD (Voice Activity Detection) loop. If it hears you speak to it, it will record and inject it as a sensory event!
