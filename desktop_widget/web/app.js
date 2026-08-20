/* Helix desktop widget: dashboard chat bridge and direct native dragging. */

document.addEventListener("DOMContentLoaded", () => {
  "use strict";

  const avatar = document.getElementById("helix-avatar-widget");
  const drawer = document.getElementById("mini-chat-drawer");
  const closeDrawerButton = document.getElementById("close-drawer");
  const closeWidgetButton = document.getElementById("close-widget");
  const chatForm = document.getElementById("chat-form");
  const chatFeed = document.getElementById("chat-feed");
  const input = document.getElementById("user-input");
  const sendButton = document.getElementById("send-prompt");
  const pasteButton = document.getElementById("paste-clipboard");
  const statusDot = document.getElementById("connection-dot");
  const statusText = document.getElementById("agent-status");
  const speechBubble = document.getElementById("speech-bubble");
  const speechText = document.getElementById("speech-bubble-text");

  let drawerOpen = false;
  let desktopBridge = null;
  let outboundCursor = 0;
  let suppressNextClick = false;
  let bubbleTimer = null;
  const drag = {
    active: false,
    moved: false,
    pointerId: null,
    startClientX: 0,
    startClientY: 0,
    startLeft: 0,
    startTop: 0,
    frame: null,
  };

  function showBubble(text, duration = 5000) {
    speechText.textContent = text;
    speechBubble.classList.add("visible");
    window.clearTimeout(bubbleTimer);
    bubbleTimer = window.setTimeout(() => speechBubble.classList.remove("visible"), duration);
  }

  function appendMessage(role, content, author) {
    const article = document.createElement("article");
    article.className = `message ${role}-message`;
    const authorNode = document.createElement("span");
    authorNode.className = "message-author";
    authorNode.textContent = author;
    const body = document.createElement("p");
    body.textContent = content;
    article.append(authorNode, body);
    chatFeed.appendChild(article);
    chatFeed.scrollTop = chatFeed.scrollHeight;
  }

  function positionBrowserDrawer() {
    if (desktopBridge || !drawerOpen) return;
    const avatarRect = avatar.getBoundingClientRect();
    const drawerRect = drawer.getBoundingClientRect();
    const left = Math.min(
      window.innerWidth - drawerRect.width - 8,
      Math.max(8, avatarRect.right - drawerRect.width),
    );
    let top = avatarRect.top - drawerRect.height - 12;
    if (top < 8) top = Math.min(window.innerHeight - drawerRect.height - 8, avatarRect.bottom + 12);
    drawer.style.left = `${Math.max(8, left)}px`;
    drawer.style.top = `${Math.max(8, top)}px`;
    drawer.style.right = "auto";
    drawer.style.bottom = "auto";
  }

  function setDrawerOpen(open) {
    drawerOpen = Boolean(open);
    drawer.classList.toggle("hidden", !drawerOpen);
    avatar.setAttribute("aria-expanded", String(drawerOpen));
    if (desktopBridge) desktopBridge.setDrawerOpen(drawerOpen);
    if (drawerOpen) {
      window.requestAnimationFrame(() => {
        positionBrowserDrawer();
        input.focus();
      });
    }
  }

  function connectNativeBridge() {
    if (!window.qt || !window.qt.webChannelTransport) return;

    const connect = () => {
      new window.QWebChannel(window.qt.webChannelTransport, (channel) => {
        desktopBridge = channel.objects.helixDesktop;
        document.body.classList.add("native-overlay");
        [avatar, drawer].forEach((element) => {
          ["left", "top", "right", "bottom"].forEach((property) => element.style.removeProperty(property));
        });
        desktopBridge.setDrawerOpen(drawerOpen);
      });
    };

    if (window.QWebChannel) {
      connect();
      return;
    }
    const script = document.createElement("script");
    script.src = "qrc:///qtwebchannel/qwebchannel.js";
    script.addEventListener("load", connect, { once: true });
    script.addEventListener("error", () => console.error("Unable to load Qt WebChannel"), { once: true });
    document.head.appendChild(script);
  }

  function moveBrowserAvatar(clientX, clientY) {
    const maxLeft = Math.max(0, window.innerWidth - avatar.offsetWidth);
    const maxTop = Math.max(0, window.innerHeight - avatar.offsetHeight);
    const left = Math.min(maxLeft, Math.max(0, drag.startLeft + clientX - drag.startClientX));
    const top = Math.min(maxTop, Math.max(0, drag.startTop + clientY - drag.startClientY));
    avatar.style.left = `${left}px`;
    avatar.style.top = `${top}px`;
    avatar.style.right = "auto";
    avatar.style.bottom = "auto";
  }

  function queueNativeMove() {
    if (!desktopBridge || drag.frame !== null) return;
    drag.frame = window.requestAnimationFrame(() => {
      drag.frame = null;
      desktopBridge.moveWindowDrag();
    });
  }

  avatar.addEventListener("pointerdown", (event) => {
    if (event.button !== 0 || event.target.closest("a, button, input, textarea")) return;
    const rect = avatar.getBoundingClientRect();
    drag.active = true;
    drag.moved = false;
    drag.pointerId = event.pointerId;
    drag.startClientX = event.clientX;
    drag.startClientY = event.clientY;
    drag.startLeft = rect.left;
    drag.startTop = rect.top;
    avatar.setPointerCapture(event.pointerId);
    avatar.classList.add("dragging");
    if (desktopBridge) desktopBridge.beginWindowDrag();
    event.preventDefault();
  });

  avatar.addEventListener("pointermove", (event) => {
    if (!drag.active || event.pointerId !== drag.pointerId) return;
    if (Math.hypot(event.clientX - drag.startClientX, event.clientY - drag.startClientY) >= 4) {
      drag.moved = true;
    }
    if (!drag.moved) return;
    if (desktopBridge) queueNativeMove();
    else moveBrowserAvatar(event.clientX, event.clientY);
  });

  function finishDrag(event) {
    if (!drag.active || (event.pointerId !== undefined && event.pointerId !== drag.pointerId)) return;
    if (drag.frame !== null) {
      window.cancelAnimationFrame(drag.frame);
      drag.frame = null;
      if (desktopBridge && drag.moved) desktopBridge.moveWindowDrag();
    }
    if (desktopBridge) desktopBridge.endWindowDrag();
    suppressNextClick = drag.moved;
    drag.active = false;
    avatar.classList.remove("dragging");
    if (avatar.hasPointerCapture(drag.pointerId)) avatar.releasePointerCapture(drag.pointerId);
    drag.pointerId = null;
    positionBrowserDrawer();
  }

  avatar.addEventListener("pointerup", finishDrag);
  avatar.addEventListener("pointercancel", finishDrag);
  avatar.addEventListener("click", (event) => {
    if (suppressNextClick) {
      suppressNextClick = false;
      event.preventDefault();
      return;
    }
    setDrawerOpen(!drawerOpen);
  });
  avatar.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      setDrawerOpen(!drawerOpen);
    }
  });

  closeDrawerButton.addEventListener("click", () => setDrawerOpen(false));
  closeWidgetButton.addEventListener("click", () => {
    if (desktopBridge) desktopBridge.closeWidget();
  });

  async function primeOutboundCursor() {
    try {
      const response = await fetch("/api/messages/outbound?since=0", { cache: "no-store" });
      const data = await response.json();
      outboundCursor = Number(data.total || 0);
    } catch (_error) {
      outboundCursor = 0;
    }
  }

  async function pollOutbound() {
    try {
      const response = await fetch(`/api/messages/outbound?since=${outboundCursor}`, { cache: "no-store" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      const messages = Array.isArray(data.messages) ? data.messages : [];
      messages.forEach((message) => {
        const content = String(message.content || "").trim();
        if (!content) return;
        appendMessage("assistant", content, "Helix");
        showBubble(content.length > 90 ? `${content.slice(0, 87)}…` : content);
      });
      outboundCursor = Number(data.total || outboundCursor + messages.length);
      statusDot.classList.add("online");
    } catch (_error) {
      statusDot.classList.remove("online");
    }
  }

  async function pollStatus() {
    try {
      const response = await fetch("/api/status", { cache: "no-store" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      const state = String(data.state || "ready").toUpperCase();
      const affect = data.affect && data.affect.dominant ? String(data.affect.dominant) : "neutral";
      statusText.textContent = `${state.toLowerCase()} · ${affect}`;
      statusDot.classList.add("online");
      avatar.classList.remove("mood-active", "mood-resting", "mood-dormant");
      if (state === "ACTIVE") avatar.classList.add("mood-active");
      else if (state === "RESTING") avatar.classList.add("mood-resting");
      else if (state === "DORMANT") avatar.classList.add("mood-dormant");
      if (window.helixMascot) window.helixMascot.setMood(state.toLowerCase());
    } catch (_error) {
      statusText.textContent = "dashboard unavailable";
      statusDot.classList.remove("online");
    }
  }

  async function sendMessage(content) {
    appendMessage("user", content, "You");
    showBubble("Thinking…", 3000);
    sendButton.disabled = true;
    if (window.helixMascot) window.helixMascot.setSpeaking(true);
    try {
      const response = await fetch("/api/messages", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
    } catch (error) {
      appendMessage("system", `Message was not queued: ${error.message}`, "Widget");
      showBubble("Dashboard connection failed.");
    } finally {
      sendButton.disabled = false;
      if (window.helixMascot) window.helixMascot.setSpeaking(false);
    }
  }

  chatForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const content = input.value.trim();
    if (!content) return;
    input.value = "";
    input.style.height = "auto";
    sendMessage(content);
  });
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      chatForm.requestSubmit();
    }
  });
  input.addEventListener("input", () => {
    input.style.height = "auto";
    input.style.height = `${Math.min(120, input.scrollHeight)}px`;
  });

  pasteButton.addEventListener("click", async () => {
    try {
      const text = await navigator.clipboard.readText();
      if (text) {
        input.value = input.value ? `${input.value}\n${text}` : text;
        input.dispatchEvent(new Event("input"));
        input.focus();
      }
    } catch (_error) {
      showBubble("Clipboard permission was not granted.");
    }
  });

  connectNativeBridge();
  primeOutboundCursor().then(pollOutbound);
  pollStatus();
  window.setInterval(pollOutbound, 1000);
  window.setInterval(pollStatus, 4000);
});
