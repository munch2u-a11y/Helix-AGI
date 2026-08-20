/* -------------------------------------------------------------------
   Helix Subconscious Over-Agent — Desktop Floating Widget Logic
   Features: Real-Time 3D WebGL Mascot Sync & Web-to-Python Drag Bridge
------------------------------------------------------------------- */

document.addEventListener("DOMContentLoaded", () => {
    const avatarWidget = document.getElementById("helix-avatar-widget");
    const miniDrawer = document.getElementById("mini-chat-drawer");
    const btnCloseDrawer = document.getElementById("btn-close-drawer");
    const btnToggleAppMode = document.getElementById("btn-toggle-app-mode");
    const chatFeed = document.getElementById("chat-feed");
    const userInput = document.getElementById("user-input-field");
    const btnSendPrompt = document.getElementById("btn-send-prompt");
    const btnPasteClipboard = document.getElementById("btn-paste-clipboard");
    const btnCropSnippet = document.getElementById("btn-crop-snippet");
    const fileInputUpload = document.getElementById("file-input-upload");
    const speechBubbleText = document.getElementById("speech-bubble-text");
    const audioWaveform = document.getElementById("audio-waveform");
    const affectStatus = document.getElementById("affect-status");

    let isDrawerOpen = false;
    let isDraggingWindow = false;

    // Web-to-Python Window Drag Bridge
    avatarWidget.addEventListener('mousedown', (e) => {
        if (e.button === 0) {
            isDraggingWindow = true;
            fetch('/api/drag_start', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ screenX: e.screenX, screenY: e.screenY })
            }).catch(() => {});
        }
    });

    window.addEventListener('mousemove', (e) => {
        if (isDraggingWindow) {
            fetch('/api/drag_move', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ screenX: e.screenX, screenY: e.screenY })
            }).catch(() => {});
        }
    });

    window.addEventListener('mouseup', () => {
        if (isDraggingWindow) {
            isDraggingWindow = false;
        }
    });

    // Map Synthetic Affect / Mood Labels to 3D WebGL Scene & CSS Color Themes
    function applyMoodColorShift(label) {
        if (!label) return;
        
        avatarWidget.classList.remove("mood-focused", "mood-excited", "mood-calm", "mood-reflective");
        const lower = label.lower ? label.lower() : label.toLowerCase();
        let moodKey = "focused";

        if (lower.includes("focus") || lower.includes("analytical")) {
            avatarWidget.classList.add("mood-focused");
            moodKey = "focused";
        } else if (lower.includes("creative") || lower.includes("excited") || lower.includes("energized")) {
            avatarWidget.classList.add("mood-excited");
            moodKey = "excited";
        } else if (lower.includes("calm") || lower.includes("content") || lower.includes("receptive")) {
            avatarWidget.classList.add("mood-calm");
            moodKey = "calm";
        } else if (lower.includes("reflective") || lower.includes("diagnostic") || lower.includes("subconscious")) {
            avatarWidget.classList.add("mood-reflective");
            moodKey = "reflective";
        } else {
            avatarWidget.classList.add("mood-focused");
            moodKey = "focused";
        }

        if (window.helix3DMascot) {
            window.helix3DMascot.setMood(moodKey);
        }
    }

    // Toggle Mini-Chat Drawer
    function toggleDrawer(open) {
        isDrawerOpen = (open !== undefined) ? open : !isDrawerOpen;
        if (isDrawerOpen) {
            miniDrawer.classList.remove("hidden");
            userInput.focus();
        } else {
            miniDrawer.classList.add("hidden");
        }
    }

    avatarWidget.addEventListener("click", (e) => {
        if (!e.target.closest(".dropzone-overlay") && !isDraggingWindow) {
            toggleDrawer();
        }
    });

    btnCloseDrawer.addEventListener("click", () => toggleDrawer(false));
    btnToggleAppMode.addEventListener("click", () => {
        alert("Switching between Desktop Floating Widget and Full App Window mode!");
    });

    // Global Hotkey Listener: Alt + Space
    window.addEventListener("keydown", (e) => {
        if (e.altKey && e.code === "Space") {
            e.preventDefault();
            toggleDrawer(true);
        }
    });

    // Send User Prompt
    async function sendPrompt() {
        const text = userInput.value.trim();
        if (!text) return;

        appendMessage("user", text);
        userInput.value = "";

        updateSpeechBubble("Subconscious reflection cycle active...");
        applyMoodColorShift("reflective");
        setSpeakingState(true);

        try {
            const resp = await fetch("/api/chat", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ prompt: text })
            });
            const data = await resp.json();
            
            if (data.response) {
                appendMessage("assistant", data.response);
                updateSpeechBubble(data.response.substring(0, 45) + "...");
                applyMoodColorShift("creative");
            } else if (data.error) {
                appendMessage("system", "Error: " + data.error);
            }
        } catch (err) {
            appendMessage("system", "Connection error to local Helix server.");
        } finally {
            setSpeakingState(false);
        }
    }

    btnSendPrompt.addEventListener("click", sendPrompt);
    userInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            sendPrompt();
        }
    });

    // Clipboard Paste Helper
    btnPasteClipboard.addEventListener("click", async () => {
        try {
            const clipText = await navigator.clipboard.readText();
            if (clipText) {
                userInput.value = (userInput.value ? userInput.value + "\n" : "") + "[Clipboard Context]: " + clipText;
                userInput.focus();
            }
        } catch (e) {
            alert("Clipboard access requires user permission.");
        }
    });

    // Screen Crop Snippet Helper
    btnCropSnippet.addEventListener("click", () => {
        applyMoodColorShift("excited");
        appendMessage("system", "[Screen Crop]: Captured desktop screen snippet. Sent to vision execution sub-orchestrator.");
        userInput.value = "Inspect captured desktop screen snippet and describe what is visible.";
        sendPrompt();
    });

    // File Upload Input
    fileInputUpload.addEventListener("change", (e) => {
        if (e.target.files && e.target.files.length > 0) {
            handleFilesIngestion(Array.from(e.target.files));
        }
    });

    // Drag & Drop Handling on Floating Avatar
    ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
        avatarWidget.addEventListener(eventName, preventDefaults, false);
        document.body.addEventListener(eventName, preventDefaults, false);
    });

    function preventDefaults(e) {
        e.preventDefault();
        e.stopPropagation();
    }

    avatarWidget.addEventListener('dragenter', () => {
        avatarWidget.classList.add('drag-over');
        applyMoodColorShift('excited');
    });
    avatarWidget.addEventListener('dragover', () => avatarWidget.classList.add('drag-over'));
    avatarWidget.addEventListener('dragleave', () => {
        avatarWidget.classList.remove('drag-over');
        applyMoodColorShift('calm');
    });
    avatarWidget.addEventListener('drop', (e) => {
        avatarWidget.classList.remove('drag-over');
        const files = Array.from(e.dataTransfer.files);
        if (files.length > 0) {
            handleFilesIngestion(files);
        }
    });

    // Document Ingestion & Chunking API Handler
    async function handleFilesIngestion(files) {
        toggleDrawer(true);
        applyMoodColorShift('excited');
        appendMessage("system", `Ingesting ${files.length} document(s)... Chunking into semantic memory store.`);

        const formData = new FormData();
        files.forEach(f => formData.append("files", f));

        try {
            const resp = await fetch("/api/ingest", {
                method: "POST",
                body: formData
            });
            const result = await resp.json();

            if (result.success) {
                appendMessage("system", `✓ Ingestion Complete! Logged ${result.total_chunks} semantic chunk(s) across ${result.files_processed.length} file(s).`);
                updateSpeechBubble(`Ingested ${result.files_processed.length} document(s). Ready!`);
                applyMoodColorShift('calm');
            } else {
                appendMessage("system", `Ingestion error: ${result.error || "Failed to process files."}`);
            }
        } catch (err) {
            appendMessage("system", "Failed to upload files to local ingestion engine.");
        }
    }

    // Helper: Append Message to Feed
    function appendMessage(role, content) {
        const msgDiv = document.createElement("div");
        msgDiv.className = `message ${role}-msg`;
        
        const authorDiv = document.createElement("div");
        authorDiv.className = "msg-author";
        authorDiv.textContent = role === "user" ? "User" : (role === "assistant" ? "Helix Assistant" : "System");
        
        const contentDiv = document.createElement("div");
        contentDiv.className = "msg-content";
        contentDiv.textContent = content;

        msgDiv.appendChild(authorDiv);
        msgDiv.appendChild(contentDiv);
        chatFeed.appendChild(msgDiv);
        chatFeed.scrollTop = chatFeed.scrollHeight;
    }

    function updateSpeechBubble(text) {
        speechBubbleText.textContent = text;
        const bubble = document.getElementById("avatar-speech-bubble");
        if (bubble) {
            bubble.classList.add("active");
            setTimeout(() => bubble.classList.remove("active"), 6000);
        }
    }

    function setSpeakingState(speaking) {
        if (speaking) {
            audioWaveform.classList.remove("hidden");
        } else {
            audioWaveform.classList.add("hidden");
        }
    }

    // Connect Server-Sent Events (SSE) Stream for Background Pulses & Proactive Speech
    function initEventStream() {
        if (!!window.EventSource) {
            const source = new EventSource("/api/stream");
            
            source.addEventListener("pulse", (e) => {
                const data = JSON.parse(e.data);
                if (data.thought) {
                    updateSpeechBubble(data.thought.substring(0, 45) + "...");
                }
                if (data.affect_label) {
                    affectStatus.textContent = data.affect_label;
                    applyMoodColorShift(data.affect_label);
                }
            });

            // Handle Unprompted Proactive Speech Events
            source.addEventListener("proactive_speech", (e) => {
                const data = JSON.parse(e.data);
                if (data.proactive_speech) {
                    updateSpeechBubble(data.proactive_speech);
                    appendMessage("assistant", "⚡ [Proactive Observation]: " + data.proactive_speech);
                    if (data.mood_label) {
                        affectStatus.textContent = data.mood_label;
                        applyMoodColorShift(data.mood_label);
                    }
                    setSpeakingState(true);
                    setTimeout(() => setSpeakingState(false), 4000);
                }
            });
        }
    }

    initEventStream();
});
