import { createApp } from '/static/base/melodiJS/index.js';
import { router } from './router.js';
import { store } from './store.js';

function startMailApp(): void {
  const mountEl = document.getElementById('mail-app');
  if (!mountEl) return;

  const app = createApp({
    template: `
      <div class="mail-spa-root">
        <router-view></router-view>
      </div>
    `,
  });

  app.use(router);
  app.use(store);
  app.mount(mountEl);
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', startMailApp);
} else {
  setTimeout(startMailApp, 0);
}
