// Recipient side (Flask version): opening the link auto-requests location, so
// the only action needed is tapping "Allow" on the browser's own prompt (that
// prompt is mandatory — it is the consent step and cannot be skipped). Each
// device joins as a member with an auto-generated name and streams its fixes.

const root = document.querySelector(".card");
const shareToken = root.dataset.shareToken;
const sessionActive = root.dataset.active === "true";
const sessionFull = root.dataset.full === "true";

const sharing = document.getElementById("sharing");
const stopBtn = document.getElementById("stop-btn");
const retry = document.getElementById("retry");
const retryBtn = document.getElementById("retry-btn");
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
function showRetry() {
  retry.classList.remove("hidden");
}
function autoName() {
  return "Guest-" + Math.random().toString(36).slice(2, 6);
}

async function ensureMembership() {
  const res = await fetch(`/api/sessions/${shareToken}/join`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ member_token: memberToken || undefined, name: autoName() }),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || "Could not join this link.");
  memberToken = data.member_token;
  localStorage.setItem(memberKey, memberToken);
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
      "Location permission was blocked, so nothing is shared. Tap “Allow "
        + "location” to try again.",
      "bad"
    );
  } else if (err.code === err.POSITION_UNAVAILABLE) {
    showMessage("Your location is currently unavailable. Try again later.", "bad");
  } else {
    showMessage("Could not get a location fix. Tap “Allow location” to retry.", "bad");
  }
  showRetry();
}

async function beginShare() {
  if (!window.isSecureContext) {
    showMessage(
      "This page must be served over HTTPS (or localhost) for location sharing.",
      "bad"
    );
    return;
  }
  if (!("geolocation" in navigator)) {
    showMessage("This browser does not support location sharing.", "bad");
    return;
  }

  sharing.classList.remove("hidden");
  retry.classList.add("hidden");
  messageEl.classList.add("hidden");

  try {
    await ensureMembership();
  } catch (e) {
    stopSharing();
    showMessage(e.message, "bad");
    return;
  }

  // Raises the browser's native "Allow location?" prompt.
  watchId = navigator.geolocation.watchPosition(sendPing, onGeoError, {
    enableHighAccuracy: true,
    maximumAge: 0,
    timeout: 20000,
  });
}

function stopSharing() {
  if (watchId !== null) {
    navigator.geolocation.clearWatch(watchId);
    watchId = null;
  }
  sharing.classList.add("hidden");
}

stopBtn.addEventListener("click", () => {
  stopSharing();
  showMessage("You stopped sharing your location.", "ok");
});
retryBtn.addEventListener("click", () => {
  retry.classList.add("hidden");
  beginShare();
});

window.addEventListener("pagehide", () => stopSharing());

// Auto-start as soon as the page loads (only if the session can be joined).
if (sessionActive && !sessionFull) {
  beginShare();
}
