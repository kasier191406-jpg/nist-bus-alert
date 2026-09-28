const apiBase = window.NIST_BUS_API_BASE || "";
const schedules = document.querySelector("#schedules");
const statusText = document.querySelector("#notification-status");
const button = document.querySelector("#enable");

function base64UrlToUint8Array(value) {
  const padding = "=".repeat((4 - value.length % 4) % 4);
  const raw = atob((value + padding).replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from([...raw].map(char => char.charCodeAt(0)));
}

async function loadSchedules() {
  const response = await fetch(`${apiBase}/api/schedules/today`);
  if (!response.ok) throw new Error("Schedule data is unavailable.");
  const data = await response.json();
  schedules.innerHTML = data.map(item => `<article class="schedule ${item.status}"><h2>${item.time}</h2><p>${item.status === "available" ? "Schedule available" : "Waiting for NIST schedule"}</p>${item.routes.length ? `<div class="routes">${item.routes.join("\n")}</div>` : ""}</article>`).join("");
}

async function enableNotifications() {
  if (!("serviceWorker" in navigator) || !("PushManager" in window)) {
    statusText.textContent = "This browser does not support Web Push.";
    return;
  }
  const permission = await Notification.requestPermission();
  if (permission !== "granted") { statusText.textContent = "Notification permission was not granted."; return; }
  const config = await (await fetch(`${apiBase}/api/config`)).json();
  if (!config.vapidPublicKey) { statusText.textContent = "Notifications are not configured on this server yet."; return; }
  const registration = await navigator.serviceWorker.register("/static/sw.js");
  const subscription = await registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: base64UrlToUint8Array(config.vapidPublicKey) });
  const response = await fetch(`${apiBase}/api/push/subscribe`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(subscription) });
  if (!response.ok) throw new Error("Could not save notification subscription.");
  statusText.textContent = "Notifications enabled on this device.";
  button.disabled = true;
}

button.addEventListener("click", () => enableNotifications().catch(error => { statusText.textContent = error.message; }));
loadSchedules().catch(error => { schedules.textContent = error.message; });
if ("serviceWorker" in navigator) navigator.serviceWorker.register("/static/sw.js");
