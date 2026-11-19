import type { ComponentDef } from '/static/base/melodiJS/melodijs.js';
import type { MailAccount, MailFolder } from '../types.js';

export const MailWorkspaceView: ComponentDef = {
  delimiters: ['[[', ']]'] as [string, string],
  data() {
    return {
      searchQuery: '',
    };
  },

  computed: {
    accounts(this: any): MailAccount[] {
      return this.$store.state.accounts || [];
    },
    activeAccount(this: any): MailAccount | null {
      return this.$store.getters.activeAccount || null;
    },
    activeAccountId(this: any): string | null {
      return this.$store.state.activeAccountId || null;
    },
    folders(this: any): MailFolder[] {
      return this.$store.state.folders || [];
    },
    activeFolderId(this: any): string | null {
      return this.$store.state.activeFolderId || null;
    },
    loadingAccounts(this: any): boolean {
      return Boolean(this.$store.state.loadingAccounts);
    },
    loadingFolders(this: any): boolean {
      return Boolean(this.$store.state.loadingFolders);
    },
  },

  methods: {
    iconUrl(this: any, name: string, fill?: string): string {
      return (window as any)._url('icons', fill ? { name, fill } : { name });
    },

    folderIcon(this: any, folderType: string): string {
      const map: Record<string, string> = {
        inbox: 'inbox',
        starred: 'star',
        sent: 'send',
        drafts: 'drafts',
        archive: 'archive',
        spam: 'report',
        trash: 'delete',
        custom: 'folder',
      };
      return map[folderType] || 'folder';
    },

    onAccountChange(this: any, event: Event) {
      const target = event.target as HTMLSelectElement;
      if (target && target.value) {
        this.$store.dispatch('selectAccount', target.value);
      }
    },

    selectFolder(this: any, folderId: string) {
      this.$store.commit('SET_ACTIVE_FOLDER', folderId);
    },

    goToAccounts(this: any) {
      this.$router.push('/accounts');
    },

    refresh(this: any) {
      this.$store.dispatch('fetchAccounts');
    },
  },

  mounted(this: any) {
    this.$store.dispatch('fetchAccounts');
  },

  template: { el: '#tpl-mail-workspace' },
};
