import type { ComponentDef } from '/static/base/melodiJS/melodijs.js';
import type {
  AutodiscoverResult,
  ConnectionTestResult,
  MailAccount,
  MailAccountFormPayload,
} from '../types.js';

function emptyForm(): MailAccountFormPayload {
  return {
    name: '',
    email_address: '',
    sender_name: '',
    provider_type: 'imap_smtp',
    imap_host: '',
    imap_port: 993,
    imap_security: 'ssl',
    smtp_host: '',
    smtp_port: 587,
    smtp_security: 'starttls',
    auth_mode: 'password',
    username: '',
    password: '',
    is_default: false,
    is_active: true,
  };
}

export const AccountsView: ComponentDef = {
  delimiters: ['[[', ']]'] as [string, string],
  data() {
    return {
      showModal: false,
      editingAccountId: null as string | null,
      form: emptyForm(),
      saving: false,
      detecting: false,
      testingForm: false,
      testingAccountId: null as string | null,
      autodiscoverInfo: null as AutodiscoverResult | null,
      testResult: null as ConnectionTestResult | null,
      formError: null as string | null,
    };
  },

  computed: {
    accounts(this: any): MailAccount[] {
      return this.$store.state.accounts || [];
    },
    loading(this: any): boolean {
      return Boolean(this.$store.state.loadingAccounts);
    },
    activeCount(this: any): number {
      return this.$store.getters.activeAccountsCount || 0;
    },
    errorCount(this: any): number {
      return this.$store.getters.errorAccountsCount || 0;
    },
    i18n(this: any): Record<string, string> {
      return (window as any).MELODI_MAILBOX_I18N || {};
    },
  },

  methods: {
    iconUrl(this: any, name: string, fill?: string): string {
      return (window as any)._url('icons', fill ? { name, fill } : { name });
    },

    goToWorkspace(this: any) {
      this.$router.push('/');
    },

    openCreateModal(this: any) {
      this.editingAccountId = null;
      this.form = emptyForm();
      this.autodiscoverInfo = null;
      this.testResult = null;
      this.formError = null;
      this.showModal = true;
    },

    openEditModal(this: any, account: MailAccount) {
      this.editingAccountId = account.account_id;
      this.form = {
        name: account.name || '',
        email_address: account.email_address || '',
        sender_name: account.sender_name || '',
        provider_type: account.provider_type || 'imap_smtp',
        imap_host: account.imap_host || '',
        imap_port: account.imap_port || 993,
        imap_security: account.imap_security || 'ssl',
        smtp_host: account.smtp_host || '',
        smtp_port: account.smtp_port || 587,
        smtp_security: account.smtp_security || 'starttls',
        auth_mode: account.auth_mode || 'password',
        username: account.username || account.email_address || '',
        password: '',
        is_default: Boolean(account.is_default),
        is_active: Boolean(account.is_active),
      };
      this.autodiscoverInfo = null;
      this.testResult = null;
      this.formError = null;
      this.showModal = true;
    },

    closeModal(this: any) {
      this.showModal = false;
      this.formError = null;
      this.testResult = null;
    },

    async runAutodiscover(this: any) {
      if (!this.form.email_address || !this.form.email_address.includes('@')) {
        this.formError = 'Saisissez une adresse email valide avant la détection.';
        return;
      }
      this.detecting = true;
      this.formError = null;
      try {
        const res: AutodiscoverResult = await this.$store.dispatch(
          'autodiscover',
          this.form.email_address
        );
        this.autodiscoverInfo = res;
        if (res) {
          this.form.imap_host = res.imap_host || this.form.imap_host;
          this.form.imap_port = res.imap_port || 993;
          this.form.imap_security = res.imap_security || 'ssl';
          this.form.smtp_host = res.smtp_host || this.form.smtp_host;
          this.form.smtp_port = res.smtp_port || 587;
          this.form.smtp_security = res.smtp_security || 'starttls';
          if (!this.form.username) {
            this.form.username = this.form.email_address;
          }
          if (!this.form.name) {
            this.form.name = this.form.email_address.split('@')[0];
          }
        }
      } catch (err: any) {
        this.formError = err?.message || 'Erreur lors de la détection automatique.';
      } finally {
        this.detecting = false;
      }
    },

    async runFormConnectionTest(this: any) {
      this.testingForm = true;
      this.formError = null;
      this.testResult = null;
      try {
        const res: ConnectionTestResult = await this.$store.dispatch('testAdHocConnection', {
          ...this.form,
        });
        this.testResult = res;
      } catch (err: any) {
        this.formError = err?.message || 'Erreur lors du test de connexion.';
      } finally {
        this.testingForm = false;
      }
    },

    async runSavedAccountTest(this: any, account: MailAccount) {
      this.testingAccountId = account.account_id;
      try {
        const res: ConnectionTestResult = await this.$store.dispatch(
          'testSavedAccount',
          account.account_id
        );
        const toast = (window as any).melodi?.toast;
        if (toast) {
          if (res?.success) {
            toast.success(this.i18n.connection_ok || 'Connexion IMAP/SMTP réussie.');
          } else {
            toast.error(res?.imap_message || res?.smtp_message || this.i18n.connection_failed);
          }
        }
      } finally {
        this.testingAccountId = null;
      }
    },

    async submitForm(this: any, event?: Event) {
      if (event) event.preventDefault();
      this.saving = true;
      this.formError = null;
      try {
        if (this.editingAccountId) {
          await this.$store.dispatch('updateAccount', {
            accountId: this.editingAccountId,
            payload: { ...this.form },
          });
        } else {
          await this.$store.dispatch('createAccount', { ...this.form });
        }
        this.closeModal();
      } catch (err: any) {
        this.formError = err?.message || 'Impossible d\'enregistrer le compte.';
      } finally {
        this.saving = false;
      }
    },

    async confirmDelete(this: any, account: MailAccount) {
      const msg =
        this.i18n.confirm_delete_account ||
        'Voulez-vous vraiment supprimer ce compte email ?';
      if (!window.confirm(msg)) return;
      await this.$store.dispatch('deleteAccount', account.account_id);
    },

    statusBadgeClass(this: any, status: string): string {
      if (status === 'error') return 'ds-badge-danger';
      if (status === 'syncing') return 'ds-badge-info';
      if (status === 'paused') return 'ds-badge-warning';
      return 'ds-badge-success';
    },

    statusLabel(this: any, status: string): string {
      const map: Record<string, string> = {
        idle: this.i18n.status_idle || 'Prêt',
        syncing: this.i18n.status_syncing || 'Synchronisation...',
        error: this.i18n.status_error || 'Erreur',
        paused: this.i18n.status_paused || 'En pause',
      };
      return map[status] || status;
    },
  },

  mounted(this: any) {
    this.$store.dispatch('fetchAccounts');
  },

  template: { el: '#tpl-mail-accounts' },
};
