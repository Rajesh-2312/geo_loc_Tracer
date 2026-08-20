// Dashboard (static build): poll the get_locations RPC with the owner key and
// render one colored marker + trail per member on a Leaflet map.

const shareToken = window.qs("t");
const ownerKey = window.qs("key");

const labelEl = document.getElementById("label");
const statusPill = document.getElementById("status-pill");
const memberCountEl = document.getElementById("member-count");
const memberListEl = document.getElementById("member-list");

const POLL_MS = 4000;
const COLORS = [
  "#0ea5e9", "#f97316", "#22c55e", "#e11d48", "#a855f7",
  "#eab308", "#14b8a6", "#ec4899", "#3b82f6", "#84cc16",
];
const IDLE_MS = 30000;

const map = L.map("map").setView([20, 0], 2);
L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 19,
  attribution: "&copy; OpenStreetMap contributors",
}).addTo(map);

const layers = {};
let fittedOnce = false;

function setStatus(cls, text) {
  statusPill.className = `pill ${cls}`;
  statusPill.textContent = text;
}
function colorFor(i) {
  return COLORS[i % COLORS.length];
}
function coloredIcon(color) {
  return L.divIcon({
    className: "member-pin",
    html: `<span style="--pin:${color}"></span>`,
    iconSize: [22, 22],
    iconAnchor: [11, 11],
  });
}
function escapeHtml(s) {
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}

function upsertMember(member, index) {
  const color = colorFor(index);
  const latest = member.latest;
  if (!latest) return;
  const point = [latest.lat, latest.lng];
  let layer = layers[member.id];
  if (!layer) {
    layer = {
      color,
      marker: L.marker(point, { icon: coloredIcon(color) }).addTo(map),
      trail: L.polyline(member.trail || [], { color, weight: 3, opacity: 0.7 }).addTo(map),
      circle: null,
    };
    layers[member.id] = layer;
  } else {
    layer.marker.setLatLng(point);
    layer.trail.setLatLngs(member.trail || []);
  }
  layer.marker.bindTooltip(member.name, { direction: "top" });
  if (layer.circle) layer.circle.remove();
  if (latest.accuracy) {
    layer.circle = L.circle(point, {
      radius: latest.accuracy,
      color,
      fillColor: color,
      fillOpacity: 0.1,
      weight: 1,
    }).addTo(map);
  }
}

function removeStaleLayers(activeIds) {
  for (const id of Object.keys(layers)) {
    if (!activeIds.has(Number(id))) {
      const l = layers[id];
      l.marker.remove();
      l.trail.remove();
      if (l.circle) l.circle.remove();
      delete layers[id];
    }
  }
}

function renderLegend(members) {
  memberListEl.innerHTML = "";
  members.forEach((m, i) => {
    const li = document.createElement("li");
    const color = colorFor(i);
    const seen = m.last_seen ? new Date(m.last_seen) : null;
    const idle = !seen || Date.now() - seen.getTime() > IDLE_MS;
    const seenText = seen
      ? `${idle ? "idle" : "live"} · ${seen.toLocaleTimeString()}`
      : "not sharing yet";
    li.innerHTML =
      `<span class="swatch" style="background:${color}"></span>` +
      `<span class="mname">${escapeHtml(m.name)}</span>` +
      `<span class="mseen ${idle ? "idle" : "live"}">${seenText}</span>`;
    memberListEl.appendChild(li);
  });
}

function fitToMembers(members) {
  const pts = members.filter((m) => m.latest).map((m) => [m.latest.lat, m.latest.lng]);
  if (pts.length === 0 || fittedOnce) return;
  if (pts.length === 1) map.setView(pts[0], 16);
  else map.fitBounds(pts, { padding: [40, 40] });
  fittedOnce = true;
}

async function poll() {
  if (!shareToken || !ownerKey) {
    setStatus("ended", "Invalid link");
    return;
  }
  const { data } = await window.rpc("get_locations", {
    p_share_token: shareToken,
    p_owner_key: ownerKey,
  });
  if (!data) {
    setStatus("ended", "Connection lost");
    return;
  }
  if (data.error) {
    setStatus("ended", data.error === "forbidden" ? "Access denied" : "Not found");
    return;
  }

  labelEl.textContent = data.label || "";
  const members = data.members || [];
  renderLegend(members);
  members.forEach((m, i) => upsertMember(m, i));
  removeStaleLayers(new Set(members.map((m) => m.id)));
  fitToMembers(members);
  memberCountEl.textContent = `${data.member_count} / ${data.max_members} joined`;

  const anyFix = members.some((m) => m.latest);
  if (!data.active) setStatus("ended", data.expired ? "Link expired" : "Session ended");
  else if (anyFix) setStatus("live", "Live");
  else setStatus("waiting", "Waiting for people to allow…");
}

poll();
setInterval(poll, POLL_MS);
