// Create-session form: POST the label, then reveal the generated links.

const form = document.getElementById("create-form");
const result = document.getElementById("result");
const errorEl = document.getElementById("error");

function showError(msg) {
  errorEl.textContent = msg;
  errorEl.classList.remove("hidden");
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  errorEl.classList.add("hidden");

  const label = document.getElementById("label").value.trim();
  if (!label) return;
  const expiryMinutes = parseInt(document.getElementById("expiry").value, 10);
  const maxMembers = parseInt(document.getElementById("max-members").value, 10);

  try {
    const res = await fetch("/api/sessions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        label,
        expiry_minutes: expiryMinutes,
        max_members: maxMembers,
      }),
    });
    const data = await res.json();
    if (!res.ok) {
      showError(data.error || "Could not create the link.");
      return;
    }

    document.getElementById("share-url").value = data.share_url;
    document.getElementById("dashboard-url").value = data.dashboard_url;
    document.getElementById("dashboard-link").href = data.dashboard_url;
    document.getElementById("qr-img").src = data.qr_url;

    if (data.expires_at) {
      const when = new Date(data.expires_at);
      document.getElementById("expiry-note").textContent =
        `This link expires on ${when.toLocaleString()}.`;
    }

    result.classList.remove("hidden");
    result.scrollIntoView({ behavior: "smooth" });
  } catch (err) {
    showError("Network error. Is the server running?");
  }
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
