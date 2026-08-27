self.addEventListener('install', (event) => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim());
});

// 处理Push事件
self.addEventListener('push', (event) => {
  try {
    const data = event.data ? event.data.json() : { title: 'Aveline', body: '收到通知', tag: 'aveline' };
    const title = data.title || 'Aveline';
    const options = {
      body: data.body || '',
      icon: '/icons/aveline.svg',
      badge: '/icons/aveline.svg',
      tag: data.tag || 'aveline',
      data: data.url ? { url: data.url } : {}
    };
    event.waitUntil(self.registration.showNotification(title, options));
  } catch (e) {
    // ignore
  }
});

// 点击通知聚焦或打开页面
self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const url = (event.notification && event.notification.data && event.notification.data.url) || '/';
  event.waitUntil(
    self.clients.matchAll({ type: 'window' }).then((clientList) => {
      for (const client of clientList) {
        if (client.url.includes(url) && 'focus' in client) return client.focus();
      }
      if (self.clients.openWindow) return self.clients.openWindow(url);
    })
  );
});
