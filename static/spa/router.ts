import { MelodiRouter } from '/static/base/melodiJS/index.js';
import type { RouteDef } from '/static/base/melodiJS/router.js';
import { MailWorkspaceView } from './views/MailWorkspaceView.js';
import { AccountsView } from './views/AccountsView.js';

const routes: RouteDef[] = [
  {
    path: '/',
    component: MailWorkspaceView,
  },
  {
    path: '/accounts',
    component: AccountsView,
  },
  {
    path: '*',
    component: MailWorkspaceView,
  },
];

export const router = new MelodiRouter({
  mode: 'hash',
  routes,
});
