// Sign-in page for phones and other computers (and this one, if it asks for the PIN too).
import { apply, load, t } from "./i18n.js";

await load();
apply();
const form = document.getElementById("login");
form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const out = document.getElementById("login-error");
  out.textContent = "";
  const res = await fetch("/api/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pin: document.getElementById("pin").value }),
  }).catch(() => null);
  if (res?.ok) return location.replace("/");
  const data = res ? await res.json().catch(() => ({})) : {};
  out.textContent = data.error || t("login.offline");
});
document.body.classList.add("ready");
