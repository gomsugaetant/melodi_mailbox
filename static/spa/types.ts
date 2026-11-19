export type MailSecurityMode = 'ssl' | 'starttls' | 'none';
export type MailAuthMode = 'password' | 'oauth2';
export type MailProviderType = 'imap_smtp' | 'gmail' | 'msgraph';
export type MailSyncStatus = 'idle' | 'syncing' | 'error' | 'paused';

export interface MailAccount {
  account_id: string;
  organization_id: string;
  owner_user_id: string;
  name: string;
  email_address: string;
  sender_name: string | null;
  provider_type: MailProviderType;
  imap_host: string | null;
  imap_port: number | null;
  imap_security: MailSecurityMode;
  smtp_host: string | null;
  smtp_port: number | null;
  smtp_security: MailSecurityMode;
  auth_mode: MailAuthMode;
  username: string | null;
  has_credentials: boolean;
  is_default: boolean;
  is_active: boolean;
  sync_status: MailSyncStatus;
  last_sync_at: string | null;
  last_error: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface MailAccountFormPayload {
  name: string;
  email_address: string;
  sender_name: string;
  provider_type: MailProviderType;
  imap_host: string;
  imap_port: number;
  imap_security: MailSecurityMode;
  smtp_host: string;
  smtp_port: number;
  smtp_security: MailSecurityMode;
  auth_mode: MailAuthMode;
  username: string;
  password: string;
  is_default: boolean;
  is_active: boolean;
}

export interface MailFolder {
  folder_id: string;
  account_id: string;
  name: string;
  remote_name: string;
  delimiter: string;
  folder_type: 'inbox' | 'sent' | 'drafts' | 'archive' | 'spam' | 'trash' | 'starred' | 'custom';
  unread_count: number;
  total_count: number;
  sort_order: number;
}

export interface AutodiscoverResult {
  detected: boolean;
  provider_label: string;
  provider_type: MailProviderType;
  imap_host: string;
  imap_port: number;
  imap_security: MailSecurityMode;
  smtp_host: string;
  smtp_port: number;
  smtp_security: MailSecurityMode;
  auth_mode: MailAuthMode;
  notes?: string | null;
}

export interface ConnectionTestResult {
  success: boolean;
  imap_ok: boolean;
  smtp_ok: boolean;
  imap_message: string;
  smtp_message: string;
  imap_latency_ms: number | null;
  smtp_latency_ms: number | null;
  imap_capabilities: string[];
  folders_detected: number;
}

export interface MailParticipant {
  name: string;
  email: string;
}

export interface MailAttachmentItem {
  attachment_id: string;
  message_id: string;
  media_id: string;
  filename: string;
  mime_type: string;
  size_bytes: number;
  content_id: string | null;
  is_inline: boolean;
  download_url: string;
  media_url?: string | null;
}

export interface MailMessageDetail {
  message_id: string;
  account_id: string;
  folder_id: string | null;
  thread_id: string | null;
  rfc_message_id: string | null;
  in_reply_to: string | null;
  references: string[];
  direction: 'inbound' | 'outbound';
  status: string;
  from_name: string;
  from_email: string;
  to: MailParticipant[];
  cc: MailParticipant[];
  bcc: MailParticipant[];
  reply_to: string | null;
  subject: string;
  snippet: string;
  body_text: string;
  body_html: string;
  is_read: boolean;
  is_starred: boolean;
  is_important: boolean;
  is_draft: boolean;
  has_attachments: boolean;
  size_bytes: number;
  send_error: string | null;
  sent_at: string | null;
  received_at: string | null;
  attachments: MailAttachmentItem[];
}

export interface MailThreadSummary {
  thread_id: string;
  account_id: string;
  subject: string;
  snippet: string;
  participants: MailParticipant[];
  message_count: number;
  unread_count: number;
  has_attachments: boolean;
  is_starred: boolean;
  last_message_at: string;
  latest_message_id: string | null;
  latest_from_name: string;
  latest_from_email: string;
  latest_is_draft: boolean;
  latest_status: string;
}

export interface MailThreadDetail {
  thread_id: string;
  account_id: string;
  subject: string;
  participants: MailParticipant[];
  message_count: number;
  messages: MailMessageDetail[];
}

export interface MailStoreState {
  accounts: MailAccount[];
  activeAccountId: string | null;
  folders: MailFolder[];
  activeFolderId: string | null;
  threads: MailThreadSummary[];
  threadsTotal: number;
  threadsPage: number;
  activeThread: MailThreadDetail | null;
  loadingAccounts: boolean;
  loadingFolders: boolean;
  loadingThreads: boolean;
  loadingThreadDetail: boolean;
  syncing: boolean;
  errorMessage: string | null;
  successMessage: string | null;
}
