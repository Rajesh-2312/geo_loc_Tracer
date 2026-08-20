// Share page (static build): look up the session, then on an explicit tap join
// as a member and stream location fixes via the ping RPC.

const shareToken = window.qs("t");
const memberKey = `tracer_member_${shareToken}`;
let memberToken = localStorage.getItem(memberKey) || null;
let watchId = null;

const labelEl = document.getElementById("label");
const countEl = document.getElementById("count");
const noticeEl = document.getElementById("notice");
const idle = document.getElementById("idle");
const sharing = document.getElementById("sharing");
const startBtn = document.getElementById("start-btn");
const stopBtn = document.getElementById("stop-btn");
const declineBtn = document.getElementById("decline-btn");
const nameInput = document.getElementById("name");
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
    idle.classList.remove("hidden");
    wireButtons();
  }
}

function wireButtons() {
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

async function ensureMembership() {
  const name = nameInput ? nameInput.value.trim() : "";
  const { data } = await window.rpc("join_session", {
    p_share_token: shareToken,
    p_name: name,
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
      "Location permission was denied, so nothing is shared. Reload and allow " +
        "it if you change your mind.",
      "bad"
    );
  } else if (err.code === err.POSITION_UNAVAILABLE) {
    showMessage("Your location is currently unavailable. Try again later.", "bad");
  } else {
    showMessage("Could not get a location fix. Sharing stopped.", "bad");
  }
}

async function startSharing() {
  if (!window.isSecureContext) {
    showMessage("This page must be served over HTTPS for location sharing.", "bad");
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
    showMessage(e.message, "bad");
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
  if (watchId !== null) {
    navigator.geolocation.clearWatch(watchId);
    watchId = null;
  }
  sharing.classList.add("hidden");
  idle.classList.add("hidden");
}

window.addEventListener("pagehide", () => stopSharing());
loadSession();
