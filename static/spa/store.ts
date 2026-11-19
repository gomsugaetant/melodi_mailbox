import { MelodiStore } from '/static/base/melodiJS/index.js';
import type {
  AutodiscoverResult,
  ConnectionTestResult,
  MailAccount,
  MailAccountFormPayload,
  MailFolder,
  MailStoreState,
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
    loadingAccounts: false,
    loadingFolders: false,
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

    async fetchFolders({ commit }: any, accountId: string) {
      if (!accountId) {
        commit('SET_FOLDERS', []);
        return;
      }
      commit('SET_LOADING_FOLDERS', true);
      try {
        const res = await getApi().get(`${API_BASE}/folders`, {
          params: { account_id: accountId },
          cache: { strategy: 'network-only' },
        });
        commit('SET_FOLDERS', res?.data || []);
      } catch {
        commit('SET_FOLDERS', []);
      } finally {
        commit('SET_LOADING_FOLDERS', false);
      }
    },

    async selectAccount({ commit, dispatch }: any, accountId: string) {
      commit('SET_ACTIVE_ACCOUNT', accountId);
      await dispatch('fetchFolders', accountId);
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
