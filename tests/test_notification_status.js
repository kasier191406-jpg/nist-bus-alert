const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "..", "frontend", "app.js"), "utf8");

async function startApp({ permission = "granted", registrations, responses }) {
  const elements = new Map();
  const status = { dataset: {}, textContent: "" };
  const button = { disabled: false, addEventListener: (_event, callback) => { button.callback = callback; } };
  const schedules = { replaceChildren() {}, append() {} };
  elements.set("#notification-status", status);
  elements.set("#enable", button);
  elements.set("#schedules", schedules);

  const rootRegistration = {
    active: { state: "activated", scriptURL: "https://site.example/sw.js" },
    pushManager: {
      getSubscription: async () => null,
      subscribe: async () => { throw new Error("Unexpected PushManager.subscribe call."); }
    }
  };
  const serviceWorker = {
    register: async () => rootRegistration,
    ready: Promise.resolve(rootRegistration),
    getRegistrations: async () => [rootRegistration, ...registrations]
  };
  const requests = [];
  const fetch = async (url, options = {}) => {
    requests.push({ url, options });
    const response = responses(url, options, requests);
    return {
      ok: response.status >= 200 && response.status < 300,
      status: response.status,
      json: async () => response.body
    };
  };
  const window = {
    NIST_BUS_API_BASE: "",
    Notification: { permission, requestPermission: async () => permission },
    PushManager: function PushManager() {},
    setInterval() {}
  };
  const document = { querySelector: selector => elements.get(selector) };
  const context = {
    window,
    document,
    navigator: { serviceWorker },
    Notification: window.Notification,
    fetch,
    atob: value => Buffer.from(value, "base64").toString("binary"),
    Uint8Array,
    console
  };

  vm.runInNewContext(source, context);
  await new Promise(resolve => setImmediate(resolve));
  return { button, requests, status };
}

test("an existing backend-registered subscription is reported without VAPID config", async () => {
  const subscription = { endpoint: "https://push.example/device", toJSON: () => ({
    endpoint: "https://push.example/device",
    keys: { p256dh: "public", auth: "auth" }
  }) };
  const oldRegistration = {
    active: { state: "activated", scriptURL: "https://site.example/static/sw.js" },
    pushManager: { getSubscription: async () => subscription }
  };
  const app = await startApp({
    registrations: [oldRegistration],
    responses: url => {
      if (url === "/api/schedules/today") return { status: 200, body: [] };
      if (url === "/api/push/status") return { status: 200, body: { active: true } };
      if (url === "/api/config") return { status: 200, body: { vapidPublicKey: "", pushConfigured: false } };
      throw new Error(`Unexpected request: ${url}`);
    }
  });

  assert.equal(app.status.dataset.state, "registered");
  assert.match(app.status.textContent, /subscription registered/);
  assert.match(app.status.textContent, /Delivery has not been verified/);
  assert.equal(app.requests.some(request => request.url === "/api/config"), false);
  assert.equal(app.requests.some(request => request.url === "/api/push/status"), true);
});

test("permission alone is not reported as enabled when no device subscription exists", async () => {
  const app = await startApp({
    registrations: [],
    responses: url => {
      if (url === "/api/schedules/today") return { status: 200, body: [] };
      throw new Error(`Unexpected request: ${url}`);
    }
  });

  assert.equal(app.status.dataset.state, "not-enabled");
  assert.match(app.status.textContent, /Permission allowed/);
  assert.match(app.status.textContent, /no push subscription exists/);
});

test("an existing local subscription is re-registered and verified with the backend", async () => {
  const subscription = {
    endpoint: "https://push.example/device",
    toJSON: () => ({
      endpoint: "https://push.example/device",
      keys: { p256dh: "public", auth: "auth" }
    })
  };
  const localRegistration = {
    active: { state: "activated", scriptURL: "https://site.example/sw.js" },
    pushManager: { getSubscription: async () => subscription }
  };
  let statusChecks = 0;
  let savedSubscription;
  const app = await startApp({
    registrations: [localRegistration],
    responses: (url, options) => {
      if (url === "/api/schedules/today") return { status: 200, body: [] };
      if (url === "/api/push/status") {
        statusChecks += 1;
        return { status: 200, body: { active: statusChecks > 1 } };
      }
      if (url === "/api/push/subscribe" && options.method === "POST") {
        savedSubscription = JSON.parse(options.body);
        return { status: 201, body: { created: true } };
      }
      throw new Error(`Unexpected request: ${url}`);
    }
  });

  assert.equal(app.status.dataset.state, "registered");
  assert.equal(statusChecks, 2);
  assert.deepEqual(savedSubscription, subscription.toJSON());
});
