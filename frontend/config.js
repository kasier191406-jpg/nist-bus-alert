const localHosts = new Set(["localhost", "127.0.0.1"]);
window.NIST_BUS_API_BASE = localHosts.has(window.location.hostname)
  ? ""
  : "https://nist-bus-alert-2.onrender.com";
