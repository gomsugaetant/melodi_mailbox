import { MelodiStore } from '/static/base/melodiJS/index.js';
import type {
  AutodiscoverResult,
  ConnectionTestResult,
  MailAccount,
  MailAccountFormPayload,
  MailFolder,
  MailStoreState,
  MailThreadDetail,
  MailThreadSummary,
} from './types.js';

const API_BASE = '/api/admin/melodi_mailbox';

function getApi(): any {
  return (window as any).melodi.api;
}

function getI18n(): Record<string, string> {
  return (window as any).MELODI_MAILBOX_I18N || {};
}

export const store = new MelodiStore({
  state: (): MailStoreState => ({
    accounts: [],
    activeAccountId: null,
    folders: [],
    activeFolderId: null,
    threads: [],
    threadsTotal: 0,
    threadsPage: 1,
    activeThread: null,
    loadingAccounts: false,
    loadingFolders: false,
    loadingThreads: false,
    loadingThreadDetail: false,
    syncing: false,
    errorMessage: null,
    successMessage: null,
  }),

  getters: {
    activeAccount(state: MailStoreState): MailAccount | null {
      if (!state.accounts.length) return null;
      return (
        state.accounts.find((a) => a.account_id === state.activeAccountId) ||
        state.accounts.find((a) => a.is_default) ||
        state.accounts[0] ||
        null
      );
    },
    activeAccountsCount(state: MailStoreState): number {
      return state.accounts.filter((a) => a.is_active).length;
    },
    errorAccountsCount(state: MailStoreState): number {
      return state.accounts.filter((a) => a.sync_status === 'error').length;
    },
  },

  mutations: {
    SET_ACCOUNTS(state: MailStoreState, accounts: MailAccount[]) {
      state.accounts = accounts || [];
      if (!state.activeAccountId && state.accounts.length > 0) {
        const def = state.accounts.find((a) => a.is_default) || state.accounts[0];
        state.activeAccountId = def.account_id;
      } else if (
        state.activeAccountId &&
        !state.accounts.some((a) => a.account_id === state.activeAccountId)
      ) {
        state.activeAccountId = state.accounts[0]?.account_id || null;
      }
    },
    SET_ACTIVE_ACCOUNT(state: MailStoreState, accountId: string | null) {
      state.activeAccountId = accountId;
    },
    SET_FOLDERS(state: MailStoreState, folders: MailFolder[]) {
      state.folders = folders || [];
      if (state.folders.length > 0) {
        const inbox = state.folders.find((f) => f.folder_type === 'inbox') || state.folders[0];
        state.activeFolderId = inbox.folder_id;
      } else {
        state.activeFolderId = null;
      }
    },
    SET_ACTIVE_FOLDER(state: MailStoreState, folderId: string | null) {
      state.activeFolderId = folderId;
    },
    SET_LOADING_ACCOUNTS(state: MailStoreState, value: boolean) {
      state.loadingAccounts = value;
    },
    SET_LOADING_FOLDERS(state: MailStoreState, value: boolean) {
      state.loadingFolders = value;
    },
    SET_THREADS(state: MailStoreState, payload: { items: MailThreadSummary[]; total: number; page: number }) {
      state.threads = payload.items || [];
      state.threadsTotal = payload.total || 0;
      state.threadsPage = payload.page || 1;
    },
    SET_ACTIVE_THREAD(state: MailStoreState, detail: MailThreadDetail | null) {
      state.activeThread = detail;
    },
    SET_LOADING_THREADS(state: MailStoreState, value: boolean) {
      state.loadingThreads = value;
    },
    SET_LOADING_THREAD_DETAIL(state: MailStoreState, value: boolean) {
      state.loadingThreadDetail = value;
    },
    SET_SYNCING(state: MailStoreState, value: boolean) {
      state.syncing = value;
    },
    SET_ERROR(state: MailStoreState, message: string | null) {
      state.errorMessage = message;
    },
    SET_SUCCESS(state: MailStoreState, message: string | null) {
      state.successMessage = message;
    },
  },

  actions: {
    async fetchAccounts({ commit, dispatch, state }: any) {
      commit('SET_LOADING_ACCOUNTS', true);
      commit('SET_ERROR', null);
      try {
        const res = await getApi().get(`${API_BASE}/accounts`, {
          cache: { strategy: 'network-only' },
        });
        const accounts: MailAccount[] = res?.data || [];
        commit('SET_ACCOUNTS', accounts);
        if (state.activeAccountId) {
          await dispatch('fetchFolders', state.activeAccountId);
        } else {
          commit('SET_FOLDERS', []);
        }
      } catch (err: any) {
        commit('SET_ERROR', err?.message || 'Erreur lors du chargement des comptes.');
      } finally {
        commit('SET_LOADING_ACCOUNTS', false);
      }
    },

    async fetchFolders({ commit, dispatch, state }: any, accountId: string) {
      if (!accountId) {
        commit('SET_FOLDERS', []);
        commit('SET_THREADS', { items: [], total: 0, page: 1 });
        return;
      }
      commit('SET_LOADING_FOLDERS', true);
      try {
        const res = await getApi().get(`${API_BASE}/folders`, {
          params: { account_id: accountId },
          cache: { strategy: 'network-only' },
        });
        commit('SET_FOLDERS', res?.data || []);
        if (state.activeFolderId) {
          await dispatch('fetchThreads', { page: 1 });
        }
      } catch {
        commit('SET_FOLDERS', []);
      } finally {
        commit('SET_LOADING_FOLDERS', false);
      }
    },

    async selectAccount({ commit, dispatch }: any, accountId: string) {
      commit('SET_ACTIVE_ACCOUNT', accountId);
      commit('SET_ACTIVE_THREAD', null);
      await dispatch('fetchFolders', accountId);
    },

    async selectFolder({ commit, dispatch }: any, folderId: string) {
      commit('SET_ACTIVE_FOLDER', folderId);
      commit('SET_ACTIVE_THREAD', null);
      await dispatch('fetchThreads', { page: 1 });
    },

    async fetchThreads(
      { commit, state }: any,
      opts: { page?: number; search?: string; unread?: boolean; starred?: boolean; has_attachments?: boolean } = {}
    ) {
      if (!state.activeAccountId) return;
      commit('SET_LOADING_THREADS', true);
      try {
        const params: Record<string, any> = {
          account_id: state.activeAccountId,
          page: opts.page || 1,
          per_page: 30,
        };
        if (state.activeFolderId && !opts.starred) {
          params.folder_id = state.activeFolderId;
        }
        if (opts.search) params.search = opts.search;
        if (opts.unread) params.unread = 'true';
        if (opts.starred) params.starred = 'true';
        if (opts.has_attachments) params.has_attachments = 'true';

        const res = await getApi().get(`${API_BASE}/threads`, {
          params,
          cache: { strategy: 'network-only' },
        });
        commit('SET_THREADS', {
          items: res?.data || [],
          total: res?.meta?.total || 0,
          page: res?.meta?.page || 1,
        });
      } finally {
        commit('SET_LOADING_THREADS', false);
      }
    },

    async fetchThreadDetail({ commit, dispatch }: any, threadId: string) {
      if (!threadId) return;
      commit('SET_LOADING_THREAD_DETAIL', true);
      try {
        const res = await getApi().get(`${API_BASE}/threads/detail`, {
          params: { id: threadId },
          cache: { strategy: 'network-only' },
        });
        const detail: MailThreadDetail | null = res?.data || null;
        commit('SET_ACTIVE_THREAD', detail);
        // Marquer automatiquement les messages non lus du fil comme lus à l'ouverture
        const unreadIds = (detail?.messages || [])
          .filter((m) => !m.is_read)
          .map((m) => m.message_id);
        if (unreadIds.length > 0) {
          await dispatch('setFlags', { messageIds: unreadIds, isRead: true, refreshAfter: false });
        }
      } finally {
        commit('SET_LOADING_THREAD_DETAIL', false);
      }
    },

    async syncAccount({ commit, dispatch, state }: any) {
      if (!state.activeAccountId) return;
      commit('SET_SYNCING', true);
      try {
        await getApi().post(
          `${API_BASE}/accounts/sync?id=${encodeURIComponent(state.activeAccountId)}`,
          { folder_id: state.activeFolderId },
          { notifyOnSuccess: getI18n().sync_done || 'Synchronisation terminée.' }
        );
        await dispatch('fetchFolders', state.activeAccountId);
      } finally {
        commit('SET_SYNCING', false);
      }
    },

    async setFlags(
      { dispatch, state }: any,
      { messageIds, isRead, isStarred, refreshAfter = true }: { messageIds: string[]; isRead?: boolean; isStarred?: boolean; refreshAfter?: boolean }
    ) {
      await getApi().post(`${API_BASE}/messages/flags`, {
        message_ids: messageIds,
        is_read: isRead,
        is_starred: isStarred,
      });
      if (refreshAfter && state.activeAccountId) {
        await dispatch('fetchThreads', { page: state.threadsPage });
        if (state.activeThread) {
          await dispatch('fetchThreadDetail', state.activeThread.thread_id);
        }
      }
    },

    async moveMessages(
      { commit, dispatch, state }: any,
      { messageIds, targetFolderType, targetFolderId }: { messageIds: string[]; targetFolderType?: string; targetFolderId?: string }
    ) {
      await getApi().post(`${API_BASE}/messages/move`, {
        message_ids: messageIds,
        target_folder_type: targetFolderType,
        target_folder_id: targetFolderId,
      });
      commit('SET_ACTIVE_THREAD', null);
      if (state.activeAccountId) {
        await dispatch('fetchFolders', state.activeAccountId);
      }
    },

    async deleteMessages({ commit, dispatch, state }: any, messageIds: string[]) {
      await getApi().post(`${API_BASE}/messages/delete`, { message_ids: messageIds });
      commit('SET_ACTIVE_THREAD', null);
      if (state.activeAccountId) {
        await dispatch('fetchFolders', state.activeAccountId);
      }
    },

    async saveDraft(_ctx: any, payload: Record<string, any>) {
      const res = await getApi().post(`${API_BASE}/messages/draft`, payload, {
        notifyOnError: false,
      });
      return res?.data;
    },

    async sendMessage({ dispatch, state }: any, payload: Record<string, any>) {
      const res = await getApi().post(`${API_BASE}/messages/send`, payload, {
        notifyOnSuccess: getI18n().message_sent || 'Message mis en file d\'envoi.',
      });
      if (state.activeAccountId) {
        await dispatch('fetchFolders', state.activeAccountId);
      }
      return res?.data;
    },

    async uploadAttachment(_ctx: any, { file, accountId, messageId }: { file: File; accountId: string; messageId?: string | null }) {
      const fd = new FormData();
      fd.append('file', file);
      fd.append('account_id', accountId);
      if (messageId) fd.append('message_id', messageId);
      const res = await getApi().upload(`${API_BASE}/attachments/upload`, fd);
      return res?.data;
    },

    async createAccount({ commit, dispatch }: any, payload: MailAccountFormPayload): Promise<MailAccount | null> {
      commit('SET_ERROR', null);
      const res = await getApi().post(`${API_BASE}/accounts`, payload, {
        notifyOnSuccess: getI18n().account_created || 'Compte ajouté.',
      });
      await dispatch('fetchAccounts');
      return res?.data || null;
    },

    async updateAccount(
      { commit, dispatch }: any,
      { accountId, payload }: { accountId: string; payload: Partial<MailAccountFormPayload> }
    ): Promise<MailAccount | null> {
      commit('SET_ERROR', null);
      const res = await getApi().put(`${API_BASE}/accounts/update?id=${encodeURIComponent(accountId)}`, payload, {
        notifyOnSuccess: getI18n().account_updated || 'Compte mis à jour.',
      });
      await dispatch('fetchAccounts');
      return res?.data || null;
    },

    async deleteAccount({ commit, dispatch }: any, accountId: string): Promise<boolean> {
      commit('SET_ERROR', null);
      await getApi().delete(`${API_BASE}/accounts/delete?id=${encodeURIComponent(accountId)}`, {
        notifyOnSuccess: getI18n().account_deleted || 'Compte supprimé.',
      });
      await dispatch('fetchAccounts');
      return true;
    },

    async autodiscover(_ctx: any, emailAddress: string): Promise<AutodiscoverResult> {
      const res = await getApi().post(
        `${API_BASE}/accounts/autodiscover`,
        { email_address: emailAddress, probe_dns: true },
        { notifyOnError: false }
      );
      return res?.data;
    },

    async testSavedAccount({ dispatch }: any, accountId: string): Promise<ConnectionTestResult> {
      const res = await getApi().post(
        `${API_BASE}/accounts/test?id=${encodeURIComponent(accountId)}`,
        { test_imap: true, test_smtp: true },
        { notifyOnError: false }
      );
      await dispatch('fetchAccounts');
      return res?.data;
    },

    async testAdHocConnection(_ctx: any, payload: Partial<MailAccountFormPayload>): Promise<ConnectionTestResult> {
      const res = await getApi().post(
        `${API_BASE}/accounts/test`,
        { ...payload, test_imap: true, test_smtp: true },
        { notifyOnError: false }
      );
      return res?.data;
    },
  },
});
