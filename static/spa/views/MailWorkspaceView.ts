import type { ComponentDef } from '/static/base/melodiJS/melodijs.js';
import type {
  MailAccount,
  MailAttachmentItem,
  MailFolder,
  MailMessageDetail,
  MailThreadDetail,
  MailThreadSummary,
} from '../types.js';

interface ComposeState {
  message_id: string | null;
  account_id: string;
  to: string;
  cc: string;
  bcc: string;
  subject: string;
  body_html: string;
  body_text: string;
  mode: 'html' | 'text';
  in_reply_to: string | null;
  references: string[];
  attachments: MailAttachmentItem[];
}

function emptyCompose(accountId: string): ComposeState {
  return {
    message_id: null,
    account_id: accountId,
    to: '',
    cc: '',
    bcc: '',
    subject: '',
    body_html: '',
    body_text: '',
    mode: 'html',
    in_reply_to: null,
    references: [],
    attachments: [],
  };
}

export const MailWorkspaceView: ComponentDef = {
  delimiters: ['[[', ']]'] as [string, string],
  data() {
    return {
      searchQuery: '',
      activeFilter: 'all' as 'all' | 'unread' | 'starred' | 'attachments',
      showRemoteImagesMap: {} as Record<string, boolean>,
      showComposer: false,
      showCcBcc: false,
      sending: false,
      uploadingAttachment: false,
      draftStatusText: '',
      compose: emptyCompose(''),
      _draftTimer: null as number | null,
      _searchTimer: null as number | null,
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
    threads(this: any): MailThreadSummary[] {
      return this.$store.state.threads || [];
    },
    activeThread(this: any): MailThreadDetail | null {
      return this.$store.state.activeThread || null;
    },
    loadingAccounts(this: any): boolean {
      return Boolean(this.$store.state.loadingAccounts);
    },
    loadingFolders(this: any): boolean {
      return Boolean(this.$store.state.loadingFolders);
    },
    loadingThreads(this: any): boolean {
      return Boolean(this.$store.state.loadingThreads);
    },
    loadingThreadDetail(this: any): boolean {
      return Boolean(this.$store.state.loadingThreadDetail);
    },
    syncing(this: any): boolean {
      return Boolean(this.$store.state.syncing);
    },
    i18n(this: any): Record<string, string> {
      return (window as any).MELODI_MAILBOX_I18N || {};
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

    formatDate(this: any, iso: string | null): string {
      if (!iso) return '';
      try {
        const d = new Date(iso);
        return d.toLocaleString(undefined, {
          day: '2-digit',
          month: 'short',
          hour: '2-digit',
          minute: '2-digit',
        });
      } catch {
        return iso;
      }
    },

    formatSize(this: any, bytes: number): string {
      if (!bytes) return '0 o';
      if (bytes < 1024) return `${bytes} o`;
      if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} Ko`;
      return `${(bytes / (1024 * 1024)).toFixed(1)} Mo`;
    },

    onAccountChange(this: any, event: Event) {
      const target = event.target as HTMLSelectElement;
      if (target && target.value) {
        this.$store.dispatch('selectAccount', target.value);
      }
    },

    selectFolder(this: any, folderId: string) {
      this.activeFilter = 'all';
      this.$store.dispatch('selectFolder', folderId);
    },

    setFilter(this: any, filter: 'all' | 'unread' | 'starred' | 'attachments') {
      this.activeFilter = filter;
      this.reloadThreads();
    },

    onSearchInput(this: any) {
      if (this._searchTimer) window.clearTimeout(this._searchTimer);
      this._searchTimer = window.setTimeout(() => {
        this.reloadThreads();
      }, 280);
    },

    reloadThreads(this: any, page = 1) {
      this.$store.dispatch('fetchThreads', {
        page,
        search: this.searchQuery,
        unread: this.activeFilter === 'unread',
        starred: this.activeFilter === 'starred',
        has_attachments: this.activeFilter === 'attachments',
      });
    },

    openThread(this: any, thread: MailThreadSummary) {
      this.$store.dispatch('fetchThreadDetail', thread.thread_id);
    },

    syncNow(this: any) {
      this.$store.dispatch('syncAccount');
    },

    goToAccounts(this: any) {
      this.$router.push('/accounts');
    },

    refresh(this: any) {
      this.$store.dispatch('fetchAccounts');
    },

    toggleStar(this: any, thread: MailThreadSummary, event?: Event) {
      if (event) event.stopPropagation();
      if (!thread.latest_message_id) return;
      this.$store.dispatch('setFlags', {
        messageIds: [thread.latest_message_id],
        isStarred: !thread.is_starred,
      });
    },

    markThreadUnread(this: any) {
      const msgs = this.activeThread?.messages || [];
      if (!msgs.length) return;
      this.$store.dispatch('setFlags', {
        messageIds: [msgs[msgs.length - 1].message_id],
        isRead: false,
      });
    },

    moveActiveThread(this: any, targetFolderType: string) {
      const msgs = this.activeThread?.messages || [];
      if (!msgs.length) return;
      this.$store.dispatch('moveMessages', {
        messageIds: msgs.map((m: MailMessageDetail) => m.message_id),
        targetFolderType,
      });
    },

    deleteActiveThread(this: any) {
      const msgs = this.activeThread?.messages || [];
      if (!msgs.length) return;
      const confirmMsg = this.i18n.confirm_delete_msg || 'Supprimer définitivement ce message ?';
      if (!window.confirm(confirmMsg)) return;
      this.$store.dispatch(
        'deleteMessages',
        msgs.map((m: MailMessageDetail) => m.message_id)
      );
    },

    hasBlockedImages(this: any, msg: MailMessageDetail): boolean {
      return Boolean(msg.body_html && msg.body_html.includes('data-blocked-src='));
    },

    isRemoteImagesShown(this: any, messageId: string): boolean {
      return Boolean(this.showRemoteImagesMap[messageId]);
    },

    allowRemoteImages(this: any, messageId: string) {
      this.showRemoteImagesMap = { ...this.showRemoteImagesMap, [messageId]: true };
    },

    buildIframeSrcdoc(this: any, msg: MailMessageDetail): string {
      let body = msg.body_html || '';
      if (this.isRemoteImagesShown(msg.message_id)) {
        body = body.replace(/src=""\s*data-blocked-src=(["'])(.*?)\1/gi, 'src=$1$2$1');
      }
      return `<!DOCTYPE html><html><head><meta charset="utf-8"><base target="_blank"><style>body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;font-size:14px;line-height:1.5;color:#0f172a;margin:8px 12px;word-break:break-word;}img{max-width:100%;height:auto;}blockquote{border-left:3px solid #cbd5e1;margin:8px 0;padding-left:10px;color:#475569;}</style></head><body>${body}</body></html>`;
    },

    // ── Composition, Réponse, Transfert & Brouillons ──────────────────────────

    openComposer(this: any, preset?: Partial<ComposeState>) {
      const acctId = preset?.account_id || this.activeAccountId || '';
      this.compose = { ...emptyCompose(acctId), ...(preset || {}) };
      this.showCcBcc = Boolean(this.compose.cc || this.compose.bcc);
      this.draftStatusText = '';
      this.showComposer = true;
    },

    replyToMessage(this: any, msg: MailMessageDetail, replyAll = false) {
      const myEmail = (this.activeAccount?.email_address || '').toLowerCase();
      const toSet = new Set<string>();
      if (msg.reply_to || msg.from_email) {
        toSet.add((msg.reply_to || msg.from_email).toLowerCase());
      }
      const ccList: string[] = [];
      if (replyAll) {
        for (const r of [...(msg.to || []), ...(msg.cc || [])]) {
          const em = (r.email || '').toLowerCase();
          if (em && em !== myEmail && !toSet.has(em)) {
            ccList.push(em);
          }
        }
      }
      const subj = msg.subject?.toLowerCase().startsWith('re:') ? msg.subject : `Re: ${msg.subject || ''}`;
      const refs = [...(msg.references || [])];
      if (msg.rfc_message_id && !refs.includes(msg.rfc_message_id)) {
        refs.push(msg.rfc_message_id);
      }
      const quoted = `<br><br><blockquote><p><strong>${msg.from_name || msg.from_email}</strong> (${this.formatDate(msg.received_at)}) :</p>${msg.body_html || ''}</blockquote>`;

      this.openComposer({
        account_id: msg.account_id,
        to: Array.from(toSet).join(', '),
        cc: ccList.join(', '),
        subject: subj,
        body_html: quoted,
        body_text: `\n\n> ${msg.body_text || ''}`,
        in_reply_to: msg.rfc_message_id,
        references: refs,
      });
    },

    forwardMessage(this: any, msg: MailMessageDetail) {
      const subj = msg.subject?.toLowerCase().startsWith('fwd:') ? msg.subject : `Fwd: ${msg.subject || ''}`;
      const quoted = `<br><br><p>---------- Message transféré ----------<br>De : ${msg.from_name || ''} &lt;${msg.from_email}&gt;<br>Objet : ${msg.subject}</p>${msg.body_html || ''}`;
      this.openComposer({
        account_id: msg.account_id,
        subject: subj,
        body_html: quoted,
        body_text: `\n\n---------- Message transféré ----------\n${msg.body_text || ''}`,
      });
    },

    closeComposer(this: any) {
      if (this._draftTimer) {
        window.clearTimeout(this._draftTimer);
        this._draftTimer = null;
      }
      this.showComposer = false;
    },

    onComposerHtmlInput(this: any, event: Event) {
      const el = event.target as HTMLElement;
      this.compose.body_html = el.innerHTML;
      this.compose.body_text = el.innerText || '';
      this.scheduleAutoDraft();
    },

    scheduleAutoDraft(this: any) {
      if (this._draftTimer) window.clearTimeout(this._draftTimer);
      this._draftTimer = window.setTimeout(() => {
        this.saveDraftNow();
      }, 1500);
    },

    async saveDraftNow(this: any) {
      if (!this.compose.account_id) return;
      try {
        const saved = await this.$store.dispatch('saveDraft', { ...this.compose });
        if (saved?.message_id) {
          this.compose.message_id = saved.message_id;
          this.draftStatusText = this.i18n.draft_saved || 'Brouillon enregistré';
        }
      } catch {
        // Ignorer silencieusement l'auto-save en cas de coupure réseau temporaire
      }
    },

    async onAttachmentSelected(this: any, event: Event) {
      const input = event.target as HTMLInputElement;
      const files = input?.files;
      if (!files || !files.length || !this.compose.account_id) return;
      this.uploadingAttachment = true;
      try {
        for (const file of Array.from(files)) {
          const res = await this.$store.dispatch('uploadAttachment', {
            file,
            accountId: this.compose.account_id,
            messageId: this.compose.message_id,
          });
          if (res?.message_id) {
            this.compose.message_id = res.message_id;
          }
          if (res?.attachment) {
            this.compose.attachments.push(res.attachment);
          }
        }
      } finally {
        this.uploadingAttachment = false;
        input.value = '';
      }
    },

    async submitSend(this: any, event?: Event) {
      if (event) event.preventDefault();
      if (!this.compose.account_id || !this.compose.to.trim()) return;
      this.sending = true;
      try {
        await this.$store.dispatch('sendMessage', {
          ...this.compose,
          async: true,
        });
        this.closeComposer();
      } finally {
        this.sending = false;
      }
    },
  },

  mounted(this: any) {
    this.$store.dispatch('fetchAccounts');
  },

  template: { el: '#tpl-mail-workspace' },
};
