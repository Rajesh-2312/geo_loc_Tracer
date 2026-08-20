// Supabase connection for the static (GitHub Pages) build.
//
// The anon key is PUBLIC by design — it is safe to ship in the browser. All
// security is enforced by the database (RLS + the SECURITY DEFINER functions in
// supabase_functions.sql). The service_role key must NEVER appear here.
window.SB = {
  url: "https://ssfttcblhbxzsfyyysqk.supabase.co",
  anon:
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9." +
    "eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InNzZnR0Y2JsaGJ4enNmeXl5c3FrIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODcyMzY0NDUsImV4cCI6MjEwMjgxMjQ0NX0." +
    "8nKBqp4TNzSvTi_6siisONLBtODhYfNjXpG8RbkOlqE",
};

// Call a Postgres function exposed via PostgREST: POST /rest/v1/rpc/<name>.
// Returns { ok, status, data } where data is the function's JSON result.
window.rpc = async function (fn, params) {
  const res = await fetch(`${window.SB.url}/rest/v1/rpc/${fn}`, {
    method: "POST",
    headers: {
      apikey: window.SB.anon,
      Authorization: `Bearer ${window.SB.anon}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(params || {}),
  });
  let data = null;
  try {
    data = await res.json();
  } catch (e) {
    data = null;
  }
  return { ok: res.ok, status: res.status, data };
};

// Read a query-string value (used for ?t=share_token and ?key=owner_key).
window.qs = function (name) {
  return new URLSearchParams(window.location.search).get(name);
};
