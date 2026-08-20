// Create-session page (static build): call the create_session RPC, then show
// the generated links + QR. Links point at share.html / dashboard.html with the
// tokens in the query string, resolved against this page's URL.

const form = document.getElementById("create-form");
const result = document.getElementById("result");
const errorEl = document.getElementById("error");

function showError(msg) {
  errorEl.textContent = msg;
  errorEl.classList.remove("hidden");
}

function absUrl(relative) {
  return new URL(relative, window.location.href).href;
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  errorEl.classList.add("hidden");

  const label = document.getElementById("label").value.trim();
  if (!label) return;
  const expiry = parseInt(document.getElementById("expiry").value, 10);
  const maxMembers = parseInt(document.getElementById("max-members").value, 10);

  const { ok, data } = await window.rpc("create_session", {
    p_label: label,
    p_expiry_minutes: expiry,
    p_max_members: maxMembers,
  });

  if (!ok || !data) {
    showError("Could not reach the database. Check the Supabase setup.");
    return;
  }
  if (data.error) {
    showError(data.error);
    return;
  }

  const shareUrl = absUrl(`share.html?t=${encodeURIComponent(data.share_token)}`);
  const dashUrl = absUrl(
    `dashboard.html?t=${encodeURIComponent(data.share_token)}&key=${encodeURIComponent(data.owner_key)}`
  );

  document.getElementById("share-url").value = shareUrl;
  document.getElementById("dashboard-url").value = dashUrl;
  document.getElementById("dashboard-link").href = dashUrl;

  if (window.QRCode && QRCode.toDataURL) {
    QRCode.toDataURL(shareUrl, { margin: 1, width: 360 }, (err, url) => {
      if (!err) document.getElementById("qr-img").src = url;
    });
  }

  if (data.expires_at) {
    document.getElementById("expiry-note").textContent =
      `This link expires on ${new Date(data.expires_at).toLocaleString()}.`;
  }

  result.classList.remove("hidden");
  result.scrollIntoView({ behavior: "smooth" });
});

// Copy-to-clipboard buttons.
document.querySelectorAll("[data-copy]").forEach((btn) => {
  btn.addEventListener("click", async () => {
    const input = document.getElementById(btn.dataset.copy);
    try {
      await navigator.clipboard.writeText(input.value);
      const original = btn.textContent;
      btn.textContent = "Copied!";
      setTimeout(() => (btn.textContent = original), 1500);
    } catch {
      input.select();
      document.execCommand("copy");
    }
  });
});
