// Recipient side: only after an explicit tap do we ask the browser for
// permission and start streaming location fixes to the backend. Each device
// first "joins" the link as a member (subject to the member cap) and remembers
// its member token so a refresh keeps the same identity.

const root = document.querySelector(".card");
const shareToken = root.dataset.shareToken;
const sessionActive = root.dataset.active === "true";
const sessionFull = root.dataset.full === "true";

const idle = document.getElementById("idle");
const sharing = document.getElementById("sharing");
const startBtn = document.getElementById("start-btn");
const stopBtn = document.getElementById("stop-btn");
const declineBtn = document.getElementById("decline-btn");
const nameInput = document.getElementById("name");
const statusEl = document.getElementById("share-status");
const messageEl = document.getElementById("message");

const memberKey = `tracer_member_${shareToken}`;
let memberToken = localStorage.getItem(memberKey) || null;
let watchId = null;

function showMessage(text, kind) {
  messageEl.textContent = text;
  messageEl.classList.remove("hidden", "ok", "bad");
  messageEl.classList.add(kind === "ok" ? "ok" : "bad");
}

function requiresSecureContext() {
  // Geolocation is blocked on non-localhost HTTP origins.
  return !window.isSecureContext;
}

async function ensureMembership() {
  // Reuse a saved token if we have one; otherwise claim a member slot.
  const name = nameInput ? nameInput.value.trim() : "";
  const res = await fetch(`/api/sessions/${shareToken}/join`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ member_token: memberToken || undefined, name }),
  });
  const data = await res.json();
  if (!res.ok) {
    throw new Error(data.error || "Could not join this link.");
  }
  memberToken = data.member_token;
  localStorage.setItem(memberKey, memberToken);
  return memberToken;
}

async function sendPing(position) {
  const { latitude, longitude, accuracy } = position.coords;
  statusEl.textContent =
    `Sharing — accuracy ±${Math.round(accuracy)} m ` +
    `(updated ${new Date().toLocaleTimeString()})`;
  try {
    const res = await fetch(`/api/sessions/${shareToken}/ping`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        member_token: memberToken,
        lat: latitude,
        lng: longitude,
        accuracy,
        client_ts: new Date().toISOString(),
      }),
    });
    if (res.status === 409) {
      stopSharing();
      showMessage("This session has ended or expired. Sharing stopped.", "bad");
    } else if (res.status === 403) {
      stopSharing();
      showMessage("Your membership is no longer valid. Reload to rejoin.", "bad");
    }
  } catch {
    statusEl.textContent = "Network hiccup — will retry on next fix.";
  }
}

function onGeoError(err) {
  stopSharing();
  if (err.code === err.PERMISSION_DENIED) {
    showMessage(
      "Location permission was denied, so nothing is shared. " +
        "You can reload and allow it if you change your mind.",
      "bad"
    );
  } else if (err.code === err.POSITION_UNAVAILABLE) {
    showMessage("Your location is currently unavailable. Try again outdoors or later.", "bad");
  } else {
    showMessage("Could not get a location fix. Sharing stopped.", "bad");
  }
}

async function startSharing() {
  if (requiresSecureContext()) {
    showMessage(
      "This page must be served over HTTPS (or localhost) for the browser to " +
        "allow location sharing. See the project README.",
      "bad"
    );
    return;
  }
  if (!("geolocation" in navigator)) {
    showMessage("This browser does not support location sharing.", "bad");
    return;
  }

  startBtn.disabled = true;
  try {
    await ensureMembership();
  } catch (e) {
    startBtn.disabled = false;
    showMessage(e.message, "bad"); // e.g. "This link is full (...)"
    return;
  }

  idle.classList.add("hidden");
  sharing.classList.remove("hidden");
  messageEl.classList.add("hidden");

  watchId = navigator.geolocation.watchPosition(sendPing, onGeoError, {
    enableHighAccuracy: true,
    maximumAge: 0,
    timeout: 20000,
  });
}

function stopSharing() {
  // A member stopping only stops their own stream; it does not end the session
  // for everyone else. Their marker simply goes stale on the dashboard.
  if (watchId !== null) {
    navigator.geolocation.clearWatch(watchId);
    watchId = null;
  }
  sharing.classList.add("hidden");
  idle.classList.add("hidden");
}

if (sessionActive && !sessionFull) {
  startBtn.addEventListener("click", startSharing);
  stopBtn.addEventListener("click", () => {
    stopSharing();
    showMessage("You stopped sharing your location.", "ok");
  });
  declineBtn.addEventListener("click", () => {
    idle.classList.add("hidden");
    showMessage("No location was shared.", "ok");
  });
}

// Best-effort: stop the watch if the page is closed.
window.addEventListener("pagehide", () => stopSharing());
