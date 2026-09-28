self.addEventListener("push", event => {
  const data = event.data ? event.data.json() : { title: "NIST Bus Alert", body: "A schedule is available.", url: "/" };
  event.waitUntil(self.registration.showNotification(data.title, { body: data.body, tag: data.tag, data: { url: data.url }, icon: "/static/icon.svg" }));
});
self.addEventListener("notificationclick", event => { event.notification.close(); event.waitUntil(clients.openWindow(event.notification.data.url || "/")); });
