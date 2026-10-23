export type User = { id: string; email: string; display_name: string; bio: string; avatar?: string; email_verified: boolean };
export type Participant = { id: string; user: User; role: string; last_read_at: string | null; is_archived: boolean; is_pinned: boolean; is_muted: boolean };
export type Attachment = { id: string; name: string; content_type: string; size: number };
export type Reaction = { id: string; emoji: string; user_id: string };
export type Message = { id: string; conversation: string; sender: User | null; external_sender_id: string; provider: "internal" | "whatsapp"; message_type: string; body: string; reply_to: string | null; status: string; created_at: string; sent_at: string | null; edited_at: string | null; client_message_id: string | null; attachments: Attachment[]; reactions: Reaction[] };
export type Conversation = { id: string; channel_type: "internal" | "whatsapp"; title: string; is_group: boolean; remote_phone: string; last_activity_at: string; participants: Participant[]; last_message: Message | null; unread_count: number };
export type Contact = { id: string; name: string; phone_number: string; email: string; notes: string; is_favorite: boolean; is_blocked: boolean; linked_user: string | null };
export type Story = { id: string; author: User; body: string; background: string; media_url: string | null; media_type: string | null; visibility: string; created_at: string; expires_at: string; view_count: number };
