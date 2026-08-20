// Share page (static build): opening the link auto-requests location, so the
// only thing the recipient does is tap "Allow" on the browser's own prompt.
// (That browser prompt is mandatory and cannot be skipped — it is the consent
// step.) A fallback button appears only if the browser needs a tap to raise the
// prompt, or if permission was denied.

const shareToken = window.qs("t");
const memberKey = `tracer_member_${shareToken}`;
let memberToken = localStorage.getItem(memberKey) || null;
let watchId = null;

const labelEl = document.getElementById("label");
const countEl = document.getElementById("count");
const noticeEl = document.getElementById("notice");
const sharing = document.getElementById("sharing");
const stopBtn = document.getElementById("stop-btn");
const retry = document.getElementById("retry");
const retryBtn = document.getElementById("retry-btn");
const statusEl = document.getElementById("share-status");
const messageEl = document.getElementById("message");

function showMessage(text, kind) {
  messageEl.textContent = text;
  messageEl.classList.remove("hidden", "ok", "bad");
  messageEl.classList.add(kind === "ok" ? "ok" : "bad");
}
function showNotice(text) {
  noticeEl.textContent = text;
  noticeEl.classList.remove("hidden");
}
function showRetry() {
  retry.classList.remove("hidden");
}

// Auto-generated, distinguishable name (no name entry needed).
function autoName() {
  return "Guest-" + Math.random().toString(36).slice(2, 6);
}

async function loadSession() {
  if (!shareToken) {
    labelEl.textContent = "(invalid link)";
    showNotice("This link is missing its token.");
    return;
  }
  const { data } = await window.rpc("session_info", { p_share_token: shareToken });
  if (!data || data.error) {
    labelEl.textContent = "(not found)";
    showNotice("This link was not found.");
    return;
  }
  labelEl.textContent = data.label;
  countEl.textContent = `${data.member_count} of ${data.max_members} people have joined this link.`;

  if (data.expired) {
    showNotice("This link has expired. No location will be shared.");
  } else if (!data.active) {
    showNotice("This tracking session has ended. No location will be shared.");
  } else if (data.full) {
    showNotice(`This link is full (${data.max_members} people already joined).`);
  } else {
    // Active — start sharing automatically.
    beginShare();
  }
}

async function ensureMembership() {
  const { data } = await window.rpc("join_session", {
    p_share_token: shareToken,
    p_name: autoName(),
    p_member_token: memberToken,
  });
  if (!data || data.error) {
    throw new Error((data && data.error) || "Could not join this link.");
  }
  memberToken = data.member_token;
  localStorage.setItem(memberKey, memberToken);
}

async function sendPing(position) {
  const { latitude, longitude, accuracy } = position.coords;
  statusEl.textContent =
    `Sharing — accuracy ±${Math.round(accuracy)} m ` +
    `(updated ${new Date().toLocaleTimeString()})`;
  const { data } = await window.rpc("ping", {
    p_share_token: shareToken,
    p_member_token: memberToken,
    p_lat: latitude,
    p_lng: longitude,
    p_accuracy: accuracy,
    p_client_ts: new Date().toISOString(),
  });
  if (data && data.error === "ended") {
    stopSharing();
    showMessage("This session has ended or expired. Sharing stopped.", "bad");
  } else if (data && data.error === "forbidden") {
    stopSharing();
    showMessage("Your membership is no longer valid. Reload to rejoin.", "bad");
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
    showRetry();
  } else if (err.code === err.POSITION_UNAVAILABLE) {
    showMessage("Your location is currently unavailable. Try again later.", "bad");
    showRetry();
  } else {
    showMessage("Could not get a location fix. Tap “Allow location” to retry.", "bad");
    showRetry();
  }
}

async function beginShare() {
  if (!window.isSecureContext) {
    showNotice("This page must be served over HTTPS for location sharing.");
    return;
  }
  if (!("geolocation" in navigator)) {
    showNotice("This browser does not support location sharing.");
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

  // This call raises the browser's native "Allow location?" prompt.
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
loadSession();
