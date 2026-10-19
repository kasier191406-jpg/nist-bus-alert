const apiBase = (window.NIST_BUS_API_BASE || "").replace(/\/$/, "");
const schedules = document.querySelector("#schedules");
const statusText = document.querySelector("#notification-status");
const button = document.querySelector("#enable");

function base64UrlToUint8Array(value) {
  const padding = "=".repeat((4 - value.length % 4) % 4);
  const raw = atob((value + padding).replace(/-/g, "+").replace(/_/g, "/"));
  const key = Uint8Array.from(raw, char => char.charCodeAt(0));
  if (key.length !== 65 || key[0] !== 4) {
    throw new Error("The server returned an invalid VAPID public key.");
  }
  return key;
}

function setNotificationStatus(state, message) {
  statusText.dataset.state = state;
  statusText.textContent = message;
  button.disabled = state === "enabling" || state === "registered" || state === "permission-denied";
}

async function requestJson(path, options) {
  const response = await fetch(`${apiBase}${path}`, options);
  let body = null;
  try {
    body = await response.json();
  } catch {
    body = null;
  }
  if (!response.ok) {
    throw new Error((body && body.detail) || `Request failed with HTTP ${response.status}.`);
  }
  return body;
}

function supportedForPush() {
  return "Notification" in window && "serviceWorker" in navigator && "PushManager" in window;
}

async function readyServiceWorker() {
  const registration = await navigator.serviceWorker.register("/sw.js", { scope: "/" });
  await navigator.serviceWorker.ready;
  if (!registration.active || registration.active.state !== "activated") {
    throw new Error("The service worker did not become active.");
  }
  return registration;
}

async function saveSubscription(subscription) {
  await requestJson("/api/push/subscribe", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(subscription)
  });
}

async function getPushConfiguration() {
  const config = await requestJson("/api/config");
  if (!config.vapidPublicKey || !config.pushConfigured) {
    throw new Error("Notifications are not configured on this server. Check its VAPID settings.");
  }
  base64UrlToUint8Array(config.vapidPublicKey);
  return config;
}

async function syncExistingSubscription(subscription) {
  const checkStatus = () => requestJson("/api/push/status", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ endpoint: subscription.endpoint })
  });
  let status = await checkStatus();
  if (!status.active) {
    await saveSubscription(subscription);
    status = await checkStatus();
  }
  if (!status.active) {
    throw new Error("The push subscription could not be confirmed as registered with the server.");
  }
  setNotificationStatus("registered", "Permission granted; service worker ready; push subscription registered on this device and backend. Delivery has not been verified.");
}

async function findSubscription(registration) {
  const registrations = await navigator.serviceWorker.getRegistrations();
  const ordered = [registration, ...registrations.filter(item => item !== registration)];
  for (const candidate of ordered) {
    const subscription = await candidate.pushManager.getSubscription();
    if (subscription) {
      return subscription;
    }
  }
  return null;
}

async function loadSchedules() {
  try {
    const data = await requestJson("/api/schedules/today");
    schedules.replaceChildren();
    for (const item of data) {
      const card = document.createElement("article");
      card.className = `schedule ${item.status}`;
      const heading = document.createElement("h2");
      heading.textContent = item.time;
      const summary = document.createElement("p");
      if (item.status === "available") {
        summary.textContent = "Schedule available";
      } else if (item.status === "no_schedule") {
        summary.textContent = "No Schedule Found";
      } else if (item.status === "error") {
        summary.textContent = `Schedule check error: ${item.error || "Unknown error."}`;
      } else {
        summary.textContent = "Waiting for NIST schedule";
      }
      card.append(heading, summary);
      if (item.routes && item.routes.length) {
        const routes = document.createElement("div");
        routes.className = "routes";
        routes.textContent = item.routes.join("\n");
        card.append(routes);
      }
      schedules.append(card);
    }
  } catch (error) {
    schedules.replaceChildren();
    const message = document.createElement("p");
    message.className = "schedule-error";
    message.textContent = `Schedule data error: ${error.message}`;
    schedules.append(message);
  }
}

async function enableNotifications() {
  if (!supportedForPush()) {
    setNotificationStatus("error", "Error: This browser does not support Web Push.");
    return;
  }
  setNotificationStatus("enabling", "Checking permission, service worker, and device subscription...");
  try {
    let permission = Notification.permission;
    if (permission === "denied") {
      setNotificationStatus("permission-denied", "Permission denied. Change this site's notification setting in your browser to enable alerts.");
      return;
    }
    const registration = await readyServiceWorker();
    let subscription = await findSubscription(registration);
    let config = null;
    if (permission === "default") {
      config = await getPushConfiguration();
      permission = await Notification.requestPermission();
    }
    if (permission !== "granted") {
      setNotificationStatus("permission-denied", "Permission denied. Change this site's notification setting in your browser to enable alerts.");
      return;
    }

    if (subscription) {
      await syncExistingSubscription(subscription);
      return;
    }

    config = config || await getPushConfiguration();
    subscription = await registration.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: base64UrlToUint8Array(config.vapidPublicKey)
    });
    await syncExistingSubscription(subscription);
  } catch (error) {
    setNotificationStatus("error", `Error: ${error.message}`);
  }
}

async function refreshNotificationStatus() {
  if (!supportedForPush()) {
    setNotificationStatus("error", "Error: This browser does not support Web Push.");
    return;
  }
  if (Notification.permission === "denied") {
    setNotificationStatus("permission-denied", "Permission denied. Change this site's notification setting in your browser to enable alerts.");
    return;
  }
  if (Notification.permission !== "granted") {
    setNotificationStatus("not-enabled", "Not enabled: browser notification permission has not been granted.");
    return;
  }
  try {
    setNotificationStatus("checking", "Permission allowed; checking service worker and device subscription...");
    const registration = await readyServiceWorker();
    const subscription = await findSubscription(registration);
    if (!subscription) {
      setNotificationStatus("not-enabled", "Permission allowed, but no push subscription exists on this device.");
      return;
    }
    await syncExistingSubscription(subscription);
  } catch (error) {
    setNotificationStatus("error", `Error: ${error.message}`);
  }
}

button.addEventListener("click", enableNotifications);
loadSchedules();
refreshNotificationStatus();
window.setInterval(loadSchedules, 60 * 1000);
