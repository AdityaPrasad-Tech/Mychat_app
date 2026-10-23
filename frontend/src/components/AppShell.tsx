"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import type { RefObject } from "react";
import { usePathname, useRouter } from "next/navigation";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { format, isToday, isYesterday } from "date-fns";
import { Archive, ArrowLeft, Bell, Check, CheckCheck, ChevronRight, ContactRound, Ellipsis, FileText, Info, LogOut, MessageCircle, Mic, Paperclip, Pencil, Plus, Search, Send, Settings, ShieldCheck, Smile, Sparkles, Trash2, UserRound, X } from "lucide-react";
import Avatar from "@/components/Avatar";
import { api } from "@/lib/api";
import { useUI } from "@/stores/ui";
import type { Contact, Conversation, Message, Story, User } from "@/types";

const nav = [
  { href: "/chats", label: "Chats", icon: MessageCircle },
  { href: "/status", label: "Status", icon: Sparkles },
  { href: "/contacts", label: "Contacts", icon: ContactRound },
  { href: "/archived", label: "Archived", icon: Archive },
  { href: "/settings", label: "Settings", icon: Settings },
];
const filters = ["All", "Unread", "Groups", "Internal", "WhatsApp"];
function preview(message: Message | null) { if (!message) return "Start the conversation"; return message.body || (message.message_type === "image" ? "Photo" : "Attachment"); }
function titleFor(c: Conversation, me: User) { return c.title || c.participants.find(p => p.user.id !== me.id)?.user.display_name || c.remote_phone || "Conversation"; }
function dayLabel(date: string) { const d = new Date(date); return isToday(d) ? "Today" : isYesterday(d) ? "Yesterday" : format(d, "MMMM d, yyyy"); }
function clientMessageId() {
  if (typeof crypto.randomUUID === "function") return crypto.randomUUID();
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, byte => byte.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

export default function AppShell() {
  const path = usePathname().replace(/\/$/, "") || "/";
  const router = useRouter();
  const queryClient = useQueryClient();
  const { filter, setFilter, infoOpen, setInfoOpen } = useUI();
  const [search, setSearch] = useState("");
  const searchInput = useRef<HTMLInputElement>(null);
  const selectedId = path.startsWith("/chats/") ? path.split("/")[2] : null;
  const section = path.startsWith("/contacts") ? "contacts" : path.startsWith("/status") ? "status" : path.startsWith("/archived") ? "archived" : path.startsWith("/settings") ? "settings" : "chats";
  const meQuery = useQuery({ queryKey: ["me"], queryFn: () => api<User>("/auth/me/"), retry: false });
  const conversationsQuery = useQuery({ queryKey: ["conversations", section === "archived"], queryFn: () => api<Conversation[]>(`/conversations/${section === "archived" ? "?archived=true" : ""}`), enabled: !!meQuery.data, refetchInterval: 5000 });
  const selectedQuery = useQuery({ queryKey: ["conversation", selectedId], queryFn: () => api<Conversation>(`/conversations/${selectedId}/`), enabled: !!meQuery.data && !!selectedId });
  const contactsQuery = useQuery({ queryKey: ["contacts"], queryFn: () => api<Contact[]>("/contacts/"), enabled: !!meQuery.data, refetchInterval: section === "contacts" ? 10000 : false });
  const storiesQuery = useQuery({ queryKey: ["stories"], queryFn: () => api<Story[]>("/stories/"), enabled: !!meQuery.data && section === "status" });
  const selected = conversationsQuery.data?.find(c => c.id === selectedId) || selectedQuery.data;
  const themeQuery = useQuery({ queryKey: ["preferences"], queryFn: () => api<{ theme: string; notifications: boolean; enter_to_send: boolean }>("/users/me/preferences/"), enabled: !!meQuery.data });
  const [socketState, setSocketState] = useState<"connecting" | "connected" | "offline">("connecting");
  const [typingUserId, setTypingUserId] = useState<string | null>(null);
  const socket = useRef<WebSocket | null>(null);
  const typingClear = useRef<ReturnType<typeof setTimeout> | null>(null);
  const previousUnread = useRef<Map<string, number> | null>(null);

  useEffect(() => { if (meQuery.isError) router.replace("/login"); }, [meQuery.isError, router]);
  useEffect(() => {
    const focusSearch = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        searchInput.current?.focus();
      }
    };
    window.addEventListener("keydown", focusSearch);
    return () => window.removeEventListener("keydown", focusSearch);
  }, []);
  useEffect(() => { if (themeQuery.data) document.documentElement.dataset.theme = themeQuery.data.theme === "system" ? "" : themeQuery.data.theme; }, [themeQuery.data]);
  useEffect(() => {
    if (!conversationsQuery.data || !meQuery.data || section === "archived") return;
    const current = new Map(conversationsQuery.data.map(conversation => [conversation.id, conversation.unread_count]));
    if (previousUnread.current && themeQuery.data?.notifications && "Notification" in window && Notification.permission === "granted" && document.visibilityState === "hidden") {
      for (const conversation of conversationsQuery.data) {
        const muted = conversation.participants.some(participant => participant.user.id === meQuery.data?.id && participant.is_muted);
        if (!muted && conversation.unread_count > (previousUnread.current.get(conversation.id) || 0)) {
          const notification = new Notification(titleFor(conversation, meQuery.data), { body: preview(conversation.last_message) });
          notification.onclick = () => { window.focus(); router.push(`/chats/${conversation.id}`); notification.close(); };
        }
      }
    }
    previousUnread.current = current;
  }, [conversationsQuery.data, meQuery.data, themeQuery.data?.notifications, router, section]);
  useEffect(() => {
    if (!meQuery.data) return;
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    let ws: WebSocket | null = null;
    let attempt = 0;
    const connect = async () => {
      setSocketState("connecting");
      try {
        const { token } = await api<{ token: string }>("/auth/websocket-token/");
        if (!active) return;
        const url = new URL(process.env.NEXT_PUBLIC_WS_URL || `${location.protocol === "https:" ? "wss:" : "ws:"}//${location.host}/ws/chat/`);
        url.searchParams.set("token", token);
        const connection = new WebSocket(url.toString());
        ws = connection;
        socket.current = connection;
        connection.onopen = () => { setSocketState("connected"); attempt = 0; if (selectedId) connection.send(JSON.stringify({ event: "subscribe", conversation_id: selectedId })); queryClient.invalidateQueries({ queryKey: ["conversations"] }); queryClient.invalidateQueries({ queryKey: ["messages"] }); };
        connection.onmessage = (event) => { try { const data = JSON.parse(event.data); if (data.event?.startsWith("message.") || data.event?.startsWith("reaction.") || data.event === "conversation.read") { queryClient.invalidateQueries({ queryKey: ["messages", data.conversation_id] }); queryClient.invalidateQueries({ queryKey: ["conversations"] }); } if (data.conversation_id === selectedId && data.user_id !== meQuery.data.id && data.event?.startsWith("typing.")) { if (typingClear.current) clearTimeout(typingClear.current); setTypingUserId(data.event === "typing.started" ? data.user_id : null); if (data.event === "typing.started") typingClear.current = setTimeout(() => setTypingUserId(null), 2500); } } catch { /* ignore malformed event */ } };
        connection.onclose = () => { setSocketState("offline"); if (active) timer = setTimeout(connect, Math.min(1000 * 2 ** attempt++, 20000)); };
        connection.onerror = () => connection.close();
      } catch {
        setSocketState("offline");
        if (active) timer = setTimeout(connect, Math.min(1000 * 2 ** attempt++, 20000));
      }
    };
    connect();
    const heartbeat = setInterval(() => { if (socket.current?.readyState === WebSocket.OPEN) socket.current.send(JSON.stringify({ event: "ping" })); }, 25000);
    return () => { active = false; clearTimeout(timer); clearInterval(heartbeat); if (typingClear.current) clearTimeout(typingClear.current); setTypingUserId(null); ws?.close(); socket.current = null; };
  }, [meQuery.data, selectedId, queryClient]);

  const visible = useMemo(() => (conversationsQuery.data || []).filter(c => {
    const name = meQuery.data ? titleFor(c, meQuery.data) : c.title;
    const matchesSearch = name.toLowerCase().includes(search.toLowerCase()) || preview(c.last_message).toLowerCase().includes(search.toLowerCase());
    const matchesFilter = filter === "All" || (filter === "Unread" && c.unread_count > 0) || (filter === "Groups" && c.is_group) || (filter === "Internal" && c.channel_type === "internal") || (filter === "WhatsApp" && c.channel_type === "whatsapp");
    return matchesSearch && matchesFilter;
  }).sort((a, b) => {
    const aPinned = a.participants.some(p => p.user.id === meQuery.data?.id && p.is_pinned);
    const bPinned = b.participants.some(p => p.user.id === meQuery.data?.id && p.is_pinned);
    return Number(bPinned) - Number(aPinned) || new Date(b.last_activity_at).getTime() - new Date(a.last_activity_at).getTime();
  }), [conversationsQuery.data, meQuery.data, search, filter]);

  if (meQuery.isLoading) return <div className="empty-chat">Loading MyChat…</div>;
  if (!meQuery.data) return null;
  const me = meQuery.data;
  return <div className="app">
    <nav className="rail" aria-label="Main navigation">
      <div className="brand-mark">m</div>
      {nav.map(item => <Link key={item.href} href={item.href} className={`rail-link ${section === item.href.slice(1) ? "active" : ""}`} aria-label={item.label} title={item.label}><item.icon size={21} /></Link>)}
      <div className="rail-spacer" />
      <Link className="rail-link" href="/profile" aria-label="Profile"><UserRound size={21} /></Link>
    </nav>
    <aside className={`sidebar ${selectedId || (section !== "chats" && section !== "archived") ? "mobile-hidden" : ""}`}>
      <div className="sidebar-head">
        <div className="brand-row"><div className="brand-text">my<span>chat</span><span style={{ color: "var(--text)" }}>.</span></div><div className="head-actions"><button className="icon-btn" aria-label="New contact" title="New contact" onClick={() => router.push("/contacts/new")}><Plus size={20} /></button><button className="icon-btn" aria-label="Settings" onClick={() => router.push("/settings")}><Ellipsis size={20} /></button></div></div>
        <label className="search"><Search size={18} /><input ref={searchInput} value={search} onChange={e => setSearch(e.target.value)} placeholder="Search conversations" aria-label="Search conversations" /><span style={{ fontSize: 11 }}>Ctrl K</span></label>
      </div>
      <div className="chips" aria-label="Conversation filters">{filters.map(f => <button key={f} className={`chip ${filter === f ? "active" : ""}`} onClick={() => setFilter(f)}>{f}</button>)}</div>
      <div className="section-label">{section === "archived" ? "Archived" : "Recent conversations"}</div>
      <div className="conversation-list">{conversationsQuery.isLoading && <div style={{ padding: 24, color: "var(--muted)" }}>Loading conversations…</div>}{conversationsQuery.isError && <div style={{ padding: 24, color: "var(--muted)" }}>Could not load conversations. <button className="text-link" onClick={() => conversationsQuery.refetch()}>Retry</button></div>}{visible.length === 0 && !conversationsQuery.isLoading && <div style={{ padding: 24, color: "var(--muted)", fontSize: 13 }}>No conversations yet. Add a contact to start chatting.</div>}{visible.map(c => {
        const name = titleFor(c, me); const own = c.participants.find(p => p.user.id === me.id);
        return <button key={c.id} className={`conversation-item ${selectedId === c.id ? "selected" : ""}`} onClick={() => router.push(`/chats/${c.id}`)}>
          <Avatar name={name} size={47} />
          <span className="conversation-copy"><span className="conversation-top"><span className="conversation-name">{name}</span><span className="conversation-time">{format(new Date(c.last_activity_at), "p")}</span></span><span className="conversation-bottom"><span className="conversation-preview">{c.channel_type === "whatsapp" ? "WhatsApp · " : ""}{preview(c.last_message)}</span>{c.unread_count > 0 ? <span className="unread">{c.unread_count}</span> : own?.is_pinned ? <span style={{ color: "var(--accent)" }}>●</span> : null}</span></span>
        </button>;
      })}</div>
      <div className="sidebar-foot"><Avatar name={me.display_name} size={34} /><span style={{ flex: 1, fontWeight: 700 }}>{me.display_name}</span><span title={socketState} style={{ width: 8, height: 8, borderRadius: 8, background: socketState === "connected" ? "var(--accent)" : "#c5aaa5" }} /></div>
    </aside>
    {selectedId ? <ChatWorkspace key={selectedId} conversation={selected} conversationId={selectedId} me={me} enterToSend={themeQuery.data?.enter_to_send ?? true} typingName={selected?.participants.find(p => p.user.id === typingUserId)?.user.display_name} onBack={() => router.push("/chats")} onInfo={() => setInfoOpen(!infoOpen)} socket={socket} /> : section === "contacts" ? <ContactsPanel contacts={contactsQuery.data || []} path={path} me={me} /> : section === "status" ? <StatusPanel stories={storiesQuery.data || []} path={path} me={me} /> : section === "settings" ? <SettingsPanel path={path} me={me} /> : section === "archived" ? <div className="workspace"><div className="empty-chat"><Archive size={50} color="var(--accent)" /><h1>Archived chats</h1><p>Select a conversation from the list to pick up where you left off.</p></div></div> : <div className="workspace"><div className="empty-chat"><div className="empty-icon"><MessageCircle size={50} /></div><h1>Good conversations start here.</h1><p>Choose a chat on the left, or add a contact to start something new.</p><button className="primary" style={{ marginTop: 20 }} onClick={() => router.push("/contacts/new")}>Start a conversation</button><p>Both people need accounts on this MyChat server. Add your friend using the email they registered with.</p></div></div>}
    {selected && infoOpen && <InfoPanel conversation={selected} contacts={contactsQuery.data || []} me={me} onClose={() => setInfoOpen(false)} />}
    {!selectedId && <div className="mobile-nav">{nav.filter(n => n.href !== "/archived").map(item => <Link key={item.href} href={item.href} className={section === item.href.slice(1) ? "active" : ""}><item.icon size={20} />{item.label}</Link>)}</div>}
  </div>;
}

function ChatWorkspace({ conversation, conversationId, me, enterToSend, typingName, onBack, onInfo, socket }: { conversation?: Conversation; conversationId: string; me: User; enterToSend: boolean; typingName?: string; onBack: () => void; onInfo: () => void; socket: RefObject<WebSocket | null> }) {
  const queryClient = useQueryClient();
  const [body, setBody] = useState("");
  const [error, setError] = useState("");
  const [replyTo, setReplyTo] = useState<Message | null>(null);
  const [emojiOpen, setEmojiOpen] = useState(false);
  const [recording, setRecording] = useState(false);
  const [recordedFile, setRecordedFile] = useState<File | null>(null);
  const [recordedUrl, setRecordedUrl] = useState("");
  const recorder = useRef<MediaRecorder | null>(null);
  const stream = useRef<MediaStream | null>(null);
  const typingTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastTypingSignal = useRef(0);
  const fileInput = useRef<HTMLInputElement>(null);
  const bottom = useRef<HTMLDivElement>(null);
  const [older, setOlder] = useState<Message[]>([]);
  const [olderHasMore, setOlderHasMore] = useState<boolean | null>(null);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const query = useQuery({ queryKey: ["messages", conversationId], queryFn: () => api<{ results: Message[]; has_more: boolean }>(`/conversations/${conversationId}/messages/`), enabled: !!conversation, refetchInterval: 5000 });
  const messages = useMemo(() => {
    const unique = new Map<string, Message>();
    for (const message of [...older, ...(query.data?.results || [])]) unique.set(message.id, message);
    return [...unique.values()].sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime() || a.id.localeCompare(b.id));
  }, [older, query.data]);
  const loadOlder = async () => {
    if (loadingOlder || !messages.length) return;
    setLoadingOlder(true);
    setError("");
    try {
      const page = await api<{ results: Message[]; has_more: boolean }>(`/conversations/${conversationId}/messages/?before=${encodeURIComponent(messages[0].created_at)}&before_id=${messages[0].id}`);
      setOlder(current => [...page.results, ...current]);
      setOlderHasMore(page.has_more);
    } catch (cause) { setError((cause as Error).message); }
    finally { setLoadingOlder(false); }
  };
  const readMutation = useMutation({ mutationFn: () => api(`/conversations/${conversationId}/read/`, { method: "POST", body: "{}" }), onSuccess: () => queryClient.invalidateQueries({ queryKey: ["conversations"] }) });
  const stopTyping = () => { if (typingTimer.current) clearTimeout(typingTimer.current); if (socket.current?.readyState === WebSocket.OPEN && lastTypingSignal.current) socket.current.send(JSON.stringify({ event: "typing.stopped", conversation_id: conversationId })); lastTypingSignal.current = 0; };
  const signalTyping = (value: string) => { if (!value.trim()) { stopTyping(); return; } if (socket.current?.readyState !== WebSocket.OPEN) return; if (Date.now() - lastTypingSignal.current > 2000) { socket.current.send(JSON.stringify({ event: "typing.started", conversation_id: conversationId })); lastTypingSignal.current = Date.now(); } if (typingTimer.current) clearTimeout(typingTimer.current); typingTimer.current = setTimeout(stopTyping, 1500); };
  useEffect(() => { if (conversation && conversation.unread_count) readMutation.mutate(); }, [conversationId, conversation?.unread_count]);
  useEffect(() => { bottom.current?.scrollIntoView({ behavior: "smooth" }); }, [query.data?.results.slice(-1)[0]?.id]);
  const send = useMutation({ mutationFn: () => {
    const endpoint = conversation?.channel_type === "whatsapp" ? "/integrations/whatsapp/messages/" : `/conversations/${conversationId}/messages/`;
    const payload = conversation?.channel_type === "whatsapp" ? { conversation_id: conversationId, type: "text", body, client_message_id: clientMessageId() } : { body, reply_to: replyTo?.id, client_message_id: clientMessageId() };
    return api<Message>(endpoint, { method: "POST", body: JSON.stringify(payload) });
  }, onSuccess: () => { stopTyping(); setBody(""); setReplyTo(null); setError(""); queryClient.invalidateQueries({ queryKey: ["messages", conversationId] }); queryClient.invalidateQueries({ queryKey: ["conversations"] }); }, onError: (e: Error) => setError(e.message) });
  const upload = useMutation({ mutationFn: (file: File) => { const data = new FormData(); data.append("file", file); return api<Message>(`/conversations/${conversationId}/attachments/`, { method: "POST", body: data }); }, onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["messages", conversationId] }); queryClient.invalidateQueries({ queryKey: ["conversations"] }); discardRecording(); setError(""); }, onError: (e: Error) => setError(e.message) });
  const editMessage = async (message: Message) => {
    const changed = window.prompt("Edit message", message.body);
    if (changed === null || changed.trim() === message.body) return;
    try { const updated = await api<Message>(`/messages/${message.id}/`, { method: "PATCH", body: JSON.stringify({ body: changed }) }); setOlder(current => current.map(item => item.id === message.id ? updated : item)); await query.refetch(); queryClient.invalidateQueries({ queryKey: ["conversations"] }); setError(""); }
    catch (cause) { setError((cause as Error).message); }
  };
  const deleteMessage = async (message: Message) => {
    if (!window.confirm("Delete this message?")) return;
    try { await api(`/messages/${message.id}/`, { method: "DELETE" }); setOlder(current => current.filter(item => item.id !== message.id)); await query.refetch(); queryClient.invalidateQueries({ queryKey: ["conversations"] }); setError(""); }
    catch (cause) { setError((cause as Error).message); }
  };
  const reactToMessage = async (message: Message) => {
    try { await api(`/messages/${message.id}/reactions/`, { method: "POST", body: JSON.stringify({ emoji: "❤️" }) }); const updated = await api<Message>(`/messages/${message.id}/`); setOlder(current => current.map(item => item.id === message.id ? updated : item)); await query.refetch(); setError(""); }
    catch (cause) { setError((cause as Error).message); }
  };
  const startRecording = async () => {
    try {
      stream.current = await navigator.mediaDevices.getUserMedia({ audio: true });
      const media = new MediaRecorder(stream.current);
      const chunks: BlobPart[] = [];
      media.ondataavailable = event => { if (event.data.size) chunks.push(event.data); };
      media.onstop = () => { const blob = new Blob(chunks, { type: media.mimeType || "audio/webm" }); const file = new File([blob], `voice-note-${Date.now()}.webm`, { type: blob.type }); setRecordedFile(file); setRecordedUrl(URL.createObjectURL(blob)); stream.current?.getTracks().forEach(track => track.stop()); setRecording(false); };
      recorder.current = media; media.start(); setRecording(true); setError("");
    } catch { setError("Microphone permission is needed to record a voice note."); }
  };
  const discardRecording = () => { if (recordedUrl) URL.revokeObjectURL(recordedUrl); setRecordedFile(null); setRecordedUrl(""); };
  const name = conversation ? titleFor(conversation, me) : "Conversation";
  let previousDay = "";
  return <main className="workspace">
    <header className="chat-head"><button className="icon-btn mobile-back" aria-label="Back to chats" onClick={onBack}><ArrowLeft size={21} /></button><Avatar name={name} size={41} /><div className="chat-head-title"><strong>{name}</strong><small>{typingName ? `${typingName} is typing…` : conversation?.is_group ? `${conversation.participants.length} members` : conversation?.channel_type === "whatsapp" ? "Business conversation" : "MyChat conversation"}</small></div><span className={`provider-pill ${conversation?.channel_type === "whatsapp" ? "whatsapp" : ""}`}>{conversation?.channel_type === "whatsapp" ? "WhatsApp" : "MyChat"}</span><button className="icon-btn" aria-label="Conversation info" onClick={onInfo}><Info size={19} /></button></header>
    <div className="messages" aria-live="polite">
      {query.isLoading && <span style={{ alignSelf: "center", color: "var(--muted)" }}>Loading messages…</span>}
      {query.isError && <span style={{ alignSelf: "center", color: "var(--muted)" }}>Messages unavailable. <button onClick={() => query.refetch()}>Retry</button></span>}
      {(olderHasMore ?? query.data?.has_more) && <button className="secondary" style={{ alignSelf: "center" }} disabled={loadingOlder} onClick={loadOlder}>{loadingOlder ? "Loading…" : "Earlier messages"}</button>}
      {messages.map(m => {
        const day = dayLabel(m.created_at);
        const showDay = day !== previousDay;
        previousDay = day;
        const replied = m.reply_to ? messages.find(item => item.id === m.reply_to) : null;
        return <div key={m.id} style={{ display: "contents" }}>
          {showDay && <span className="date-separator">{day}</span>}
          <div className={`bubble-row ${m.sender?.id === me.id ? "outgoing" : "incoming"}`}>
            <div className="bubble">
              {m.reply_to && <div style={{ borderLeft: "2px solid var(--accent)", paddingLeft: 8, fontSize: 11, color: "var(--muted)", marginBottom: 6 }}>{replied?.body || "Reply to earlier message"}</div>}
              {m.attachments.map(a => <div className="message-media" key={a.id}>{a.content_type.startsWith("image/") ? <img src={`/api/v1/attachments/${a.id}/download/`} alt={a.name} loading="lazy" /> : a.content_type.startsWith("video/") ? <video src={`/api/v1/attachments/${a.id}/download/`} controls preload="metadata" /> : a.content_type.startsWith("audio/") ? <audio src={`/api/v1/attachments/${a.id}/download/`} controls preload="metadata" /> : null}<a href={`/api/v1/attachments/${a.id}/download/`} target="_blank" rel="noreferrer"><FileText size={16} />{a.name}</a></div>)}
              <p>{m.body}</p>
              {m.reactions.length > 0 && <div className="bubble-reactions">{m.reactions.map(r => r.emoji).join(" ")}</div>}
              <div className="bubble-meta">{m.edited_at && "edited · "}{format(new Date(m.created_at), "p")}{m.sender?.id === me.id && (m.status === "read" ? <CheckCheck size={13} color="var(--accent-dark)" /> : m.status === "delivered" ? <CheckCheck size={13} /> : <Check size={13} />)}</div>
            </div>
            {conversation?.channel_type === "internal" && <div className="message-actions">
              <button className="icon-btn" style={{ width: 26, height: 26 }} onClick={() => setReplyTo(m)} aria-label="Reply"><ChevronRight size={15} /></button>
              <button className="icon-btn" style={{ width: 26, height: 26 }} onClick={() => reactToMessage(m)} aria-label="Toggle heart reaction"><Smile size={15} /></button>
              {m.sender?.id === me.id && <><button className="icon-btn" style={{ width: 26, height: 26 }} onClick={() => editMessage(m)} aria-label="Edit message"><Pencil size={15} /></button><button className="icon-btn" style={{ width: 26, height: 26 }} onClick={() => deleteMessage(m)} aria-label="Delete message"><Trash2 size={15} /></button></>}
            </div>}
          </div>
        </div>;
      })}
      <div ref={bottom} />
    </div>
    <div className="composer-wrap">
      {replyTo && <div style={{ fontSize: 12, paddingBottom: 10, display: "flex", alignItems: "center", gap: 10 }}>Replying to: {replyTo.body.slice(0, 70)} <button className="icon-btn" onClick={() => setReplyTo(null)} aria-label="Cancel reply"><X size={14} /></button></div>}
      {recordedFile && <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}><audio src={recordedUrl} controls aria-label="Voice note preview" /><button className="secondary" disabled={upload.isPending} onClick={() => upload.mutate(recordedFile)}>{upload.isPending ? "Sending…" : "Send voice note"}</button><button className="icon-btn" onClick={discardRecording} aria-label="Discard voice note"><X size={16} /></button></div>}
      {error && <div className="auth-error">{error}</div>}
      <div className="composer"><button className="icon-btn" aria-label="Choose emoji" onClick={() => setEmojiOpen(!emojiOpen)}><Smile size={21} /></button>
        {conversation?.channel_type === "internal" && <><input hidden ref={fileInput} type="file" accept="image/*,video/*,audio/*,audio/webm,.pdf,.txt" onChange={e => { const file = e.target.files?.[0]; if (file) upload.mutate(file); e.target.value = ""; }} /><button className="icon-btn" aria-label="Attach file" onClick={() => fileInput.current?.click()}><Paperclip size={21} /></button><button className="icon-btn" aria-label={recording ? "Stop recording" : "Record voice note"} onClick={() => recording ? recorder.current?.stop() : startRecording()}><Mic size={20} color={recording ? "#d65151" : undefined} /></button></>}
        {emojiOpen && <div style={{ position: "absolute", bottom: 85, left: 30, background: "var(--panel)", border: "1px solid var(--line)", borderRadius: 10, padding: 8 }}>{["😀", "😊", "❤️", "👍", "🎉"].map(e => <button key={e} className="icon-btn" onClick={() => { setBody(body + e); setEmojiOpen(false); }}>{e}</button>)}</div>}
        <textarea className="composer-input" rows={1} placeholder={conversation?.channel_type === "whatsapp" ? "Message your customer…" : "Type a message…"} value={body} maxLength={4096} onChange={e => { setBody(e.target.value); signalTyping(e.target.value); }} onKeyDown={e => { if (enterToSend && e.key === "Enter" && !e.shiftKey) { e.preventDefault(); if (body.trim() && !send.isPending) send.mutate(); } }} /><button className="send-btn" aria-label="Send message" disabled={!body.trim() || send.isPending} onClick={() => send.mutate()}><Send size={19} /></button></div><p className="composer-note">{enterToSend ? "Press Enter to send · Shift + Enter for a new line" : "Press Send to send · Enter for a new line"}{conversation?.channel_type === "whatsapp" ? " · Meta messaging rules apply" : ""}</p></div>
  </main>;
}

function InfoPanel({ conversation, contacts, me, onClose }: { conversation: Conversation; contacts: Contact[]; me: User; onClose: () => void }) {
  const queryClient = useQueryClient();
  const own = conversation.participants.find(p => p.user.id === me.id);
  const name = titleFor(conversation, me);
  const action = async (kind: string, value: boolean) => {
    try {
      const updated = await api<Conversation>(`/conversations/${conversation.id}/${kind}/`, { method: "POST", body: JSON.stringify({ value }) });
      queryClient.setQueryData(["conversation", conversation.id], updated);
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
    } catch (cause) { window.alert((cause as Error).message); }
  };
  return <aside className="info-panel">
    <div className="info-title">Conversation info<button className="icon-btn" aria-label="Close info" onClick={onClose}><X size={18} /></button></div>
    <div className="info-person"><Avatar name={name} size={80} /><h3>{name}</h3><small>{conversation.channel_type === "whatsapp" ? `WhatsApp Business · ${conversation.remote_phone}` : conversation.is_group ? `${conversation.participants.length} members` : "MyChat contact"}</small></div>
    <div className="info-section"><h4>Preferences</h4><button className="info-row" onClick={() => action("mute", !own?.is_muted)}><Bell size={17} />{own?.is_muted ? "Unmute notifications" : "Mute notifications"}</button><button className="info-row" onClick={() => action("pin", !own?.is_pinned)}><Sparkles size={17} />{own?.is_pinned ? "Unpin chat" : "Pin chat"}</button><button className="info-row" onClick={() => action("archive", !own?.is_archived)}><Archive size={17} />{own?.is_archived ? "Unarchive chat" : "Archive chat"}</button></div>
    {conversation.is_group && <GroupManagement conversation={conversation} contacts={contacts} me={me} onClose={onClose} />}
    <div className="info-section"><div className="info-row"><ShieldCheck size={17} />Messages are stored on MyChat servers</div></div>
  </aside>;
}

function GroupManagement({ conversation, contacts, me, onClose }: { conversation: Conversation; contacts: Contact[]; me: User; onClose: () => void }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [newTitle, setNewTitle] = useState(conversation.title);
  const [newMemberId, setNewMemberId] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const isAdmin = conversation.participants.some(p => p.user.id === me.id && p.role === "admin");
  const available = contacts.filter(c => c.linked_user && !c.is_blocked && !conversation.participants.some(p => p.user.id === c.linked_user));
  const refresh = (updated?: Conversation) => {
    if (updated) {
      queryClient.setQueryData(["conversation", conversation.id], updated);
      queryClient.setQueriesData<Conversation[]>({ queryKey: ["conversations"] }, current => current?.map(item => item.id === updated.id ? updated : item));
    }
    queryClient.invalidateQueries({ queryKey: ["conversations"] });
  };
  const run = async (task: () => Promise<Conversation | void>, leave = false) => {
    setBusy(true); setError("");
    try {
      const updated = await task();
      if (leave) { queryClient.removeQueries({ queryKey: ["conversation", conversation.id] }); refresh(); onClose(); router.push("/chats"); }
      else if (updated) refresh(updated);
      else refresh();
    } catch (cause) { setError((cause as Error).message); }
    finally { setBusy(false); }
  };
  return <div className="info-section">
    <h4>Group</h4>
    {error && <div className="auth-error">{error}</div>}
    {isAdmin && <><label className="field">Group name<input value={newTitle} onChange={event => setNewTitle(event.target.value)} maxLength={120} /></label><button className="secondary" disabled={busy || !newTitle.trim() || newTitle.trim() === conversation.title} onClick={() => run(() => api<Conversation>(`/groups/${conversation.id}/`, { method: "PATCH", body: JSON.stringify({ title: newTitle.trim() }) }))}>Rename group</button></>}
    <h4 style={{ marginTop: 24 }}>Members</h4>
    {conversation.participants.map(p => <div className="group-member" key={p.id}><Avatar name={p.user.display_name} size={30} /><span>{p.user.display_name}{p.role === "admin" ? " · admin" : ""}</span>{isAdmin && p.user.id !== me.id && <button className="text-link danger" disabled={busy} aria-label={`Remove ${p.user.display_name}`} onClick={() => { if (window.confirm(`Remove ${p.user.display_name} from this group?`)) run(async () => { await api(`/groups/${conversation.id}/members/${p.user.id}/`, { method: "DELETE" }); return api<Conversation>(`/groups/${conversation.id}/`); }); }}>Remove</button>}</div>)}
    {isAdmin && available.length > 0 && <><label className="field" style={{ marginTop: 18 }}>Add contact<select value={newMemberId} onChange={event => setNewMemberId(event.target.value)}><option value="">Choose a contact</option>{available.map(c => <option key={c.id} value={c.linked_user!}>{c.name}</option>)}</select></label><button className="secondary" disabled={busy || !newMemberId} onClick={() => run(async () => { const updated = await api<Conversation>(`/groups/${conversation.id}/members/`, { method: "POST", body: JSON.stringify({ user_id: newMemberId }) }); setNewMemberId(""); return updated; })}>Add member</button></>}
    <button className="info-row danger" disabled={busy} onClick={() => { if (window.confirm("Leave this group?")) run(async () => { await api(`/groups/${conversation.id}/members/${me.id}/`, { method: "DELETE" }); }, true); }}>Leave group</button>
  </div>;
}

function ContactsPanel({ contacts, path, me }: { contacts: Contact[]; path: string; me: User }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [notes, setNotes] = useState("");
  const [groupName, setGroupName] = useState("");
  const [memberIds, setMemberIds] = useState<string[]>([]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [editing, setEditing] = useState(false);
  const selectedId = path.split("/")[2];
  const selected = contacts.find(c => c.id === selectedId);
  const eligibleContacts = contacts.filter(c => c.linked_user && c.linked_user !== me.id && !c.is_blocked);
  useEffect(() => {
    setError(""); setNotice(""); setEditing(false);
    if (selected) { setName(selected.name); setEmail(selected.email); setPhone(selected.phone_number); setNotes(selected.notes); }
    else if (path.endsWith("/new")) { setName(""); setEmail(""); setPhone(""); setNotes(""); }
  }, [selected?.id, path]);
  const create = useMutation({ mutationFn: () => api<Contact>("/contacts/", { method: "POST", body: JSON.stringify({ name, email, phone_number: phone, notes }) }), onSuccess: c => { queryClient.invalidateQueries({ queryKey: ["contacts"] }); router.push(`/contacts/${c.id}`); }, onError: (e: Error) => setError(e.message) });
  const start = useMutation({ mutationFn: () => api<Conversation>("/conversations/", { method: "POST", body: JSON.stringify({ user_ids: [selected?.linked_user] }) }), onSuccess: c => { queryClient.invalidateQueries({ queryKey: ["conversations"] }); router.push(`/chats/${c.id}`); }, onError: (e: Error) => setError(e.message) });
  const createGroup = useMutation({ mutationFn: () => api<Conversation>("/groups/", { method: "POST", body: JSON.stringify({ title: groupName, user_ids: memberIds }) }), onSuccess: c => { queryClient.invalidateQueries({ queryKey: ["conversations"] }); router.push(`/chats/${c.id}`); }, onError: (e: Error) => setError(e.message) });
  const remove = useMutation({ mutationFn: () => api(`/contacts/${selectedId}/`, { method: "DELETE" }), onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["contacts"] }); router.push("/contacts"); }, onError: (cause: Error) => setError(cause.message) });
  const updateContact = async (changes: Record<string, unknown>, message: string) => {
    if (!selected) return false;
    try {
      await api<Contact>(`/contacts/${selected.id}/`, { method: "PATCH", body: JSON.stringify(changes) });
      await queryClient.invalidateQueries({ queryKey: ["contacts"] });
      setNotice(message); setError("");
      return true;
    } catch (cause) { setError((cause as Error).message); return false; }
  };
  const saveContact = async () => { if (await updateContact({ name, email, phone_number: phone, notes }, "Contact saved.")) setEditing(false); };
  return <main className="workspace"><div className="panel-page">
    <h1>{path.endsWith("/new") ? "New contact" : path.endsWith("/group") ? "New group" : selected ? selected.name : "Your contacts"}</h1>
    <p className="sub">Add a friend with the email they used to register on this MyChat server, then open their contact and start a conversation.</p>
    {error && <div className="auth-error">{error}</div>}
    {notice && <div style={{ color: "var(--accent-dark)", fontSize: 13, marginBottom: 14 }}>{notice}</div>}
    {path.endsWith("/new") ? <form className="card" style={{ maxWidth: 520 }} onSubmit={event => { event.preventDefault(); create.mutate(); }}>
      <label className="field">Friend&apos;s name<input value={name} onChange={event => setName(event.target.value)} required maxLength={100} /></label>
      <label className="field">Their MyChat email<input type="email" value={email} onChange={event => setEmail(event.target.value)} placeholder="friend@example.com" /></label>
      <p className="sub">Use the exact email on their MyChat account. A phone number alone cannot start an internal chat.</p>
      <label className="field">Phone number (optional, E.164)<input placeholder="+14155552671" value={phone} onChange={event => setPhone(event.target.value)} /></label>
      <label className="field">Notes<textarea value={notes} onChange={event => setNotes(event.target.value)} /></label>
      <button className="primary" type="submit" disabled={!name.trim() || create.isPending}>{create.isPending ? "Saving…" : "Save contact"}</button>
      <button className="secondary" type="button" style={{ marginLeft: 8 }} onClick={() => router.push("/contacts")}>Cancel</button>
    </form>
    : path.endsWith("/group") ? <div className="card" style={{ maxWidth: 520 }}>
      <label className="field">Group name<input value={groupName} onChange={event => setGroupName(event.target.value)} maxLength={120} /></label>
      <div className="field">Choose at least two registered MyChat contacts</div>
      {eligibleContacts.map(contact => <label key={contact.id} className="info-row"><input type="checkbox" checked={memberIds.includes(contact.linked_user!)} onChange={event => setMemberIds(event.target.checked ? [...memberIds, contact.linked_user!] : memberIds.filter(id => id !== contact.linked_user))} />{contact.name}</label>)}
      {eligibleContacts.length < 2 && <p className="sub">Add two friends using their registered MyChat email addresses first.</p>}
      <button className="primary" disabled={!groupName.trim() || memberIds.length < 2 || createGroup.isPending} onClick={() => createGroup.mutate()}>{createGroup.isPending ? "Creating…" : "Create group"}</button>
      <button className="secondary" style={{ marginLeft: 8 }} onClick={() => router.push("/contacts")}>Cancel</button>
    </div>
    : selected ? <div className="card" style={{ maxWidth: 560 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 15, marginBottom: 20 }}><Avatar name={selected.name} size={62} /><div><strong>{selected.name}</strong><div style={{ color: "var(--muted)", fontSize: 13 }}>{selected.email || selected.phone_number || "No email or phone"}</div></div></div>
      {editing ? <form onSubmit={event => { event.preventDefault(); saveContact(); }}>
        <label className="field">Name<input value={name} onChange={event => setName(event.target.value)} required maxLength={100} /></label>
        <label className="field">MyChat email<input type="email" value={email} onChange={event => setEmail(event.target.value)} /></label>
        <label className="field">Phone number (E.164)<input value={phone} onChange={event => setPhone(event.target.value)} /></label>
        <label className="field">Notes<textarea value={notes} onChange={event => setNotes(event.target.value)} /></label>
        <button className="primary" type="submit" disabled={!name.trim()}>Save changes</button>
        <button className="secondary" type="button" style={{ marginLeft: 8 }} onClick={() => setEditing(false)}>Cancel</button>
      </form> : <>
        {selected.notes && <p style={{ fontSize: 13, color: "var(--muted)" }}>{selected.notes}</p>}
        {selected.linked_user && selected.linked_user !== me.id && !selected.is_blocked && <button className="primary" disabled={start.isPending} onClick={() => start.mutate()}>{start.isPending ? "Opening…" : "Start MyChat conversation"}</button>}
        {selected.is_blocked && <p className="sub">This contact is blocked. Unblock them to chat.</p>}
        {!selected.is_blocked && !selected.linked_user && <p className="sub">No MyChat account is linked yet. Ask your friend to register with {selected.email || "an email address"} on this same server, then check again.</p>}
        {!selected.is_blocked && selected.linked_user === me.id && <p className="sub">This is your own account. Add a friend&apos;s email to start a chat.</p>}
        {!selected.linked_user && !!selected.email && <button className="secondary" onClick={() => updateContact({ email: selected.email }, "Checked for a matching account.")}>Check again</button>}
        <button className="secondary" style={{ marginLeft: 8 }} onClick={() => setEditing(true)}>Edit contact</button>
        <button className="secondary" style={{ marginLeft: 8 }} onClick={() => updateContact({ is_favorite: !selected.is_favorite }, selected.is_favorite ? "Removed from favorites." : "Added to favorites.")}>{selected.is_favorite ? "Remove favorite" : "Add favorite"}</button>
        <button className="secondary" style={{ marginLeft: 8 }} onClick={() => updateContact({ is_blocked: !selected.is_blocked }, selected.is_blocked ? "Contact unblocked." : "Contact blocked.")}>{selected.is_blocked ? "Unblock" : "Block"}</button>
        <button className="secondary danger" style={{ marginLeft: 8 }} disabled={remove.isPending} onClick={() => { if (window.confirm("Delete this contact?")) remove.mutate(); }}>Delete contact</button>
      </>}
    </div>
    : <><button className="primary" onClick={() => router.push("/contacts/new")}><Plus size={15} style={{ display: "inline", marginRight: 5 }} />Add contact</button><button className="secondary" style={{ marginLeft: 8 }} onClick={() => router.push("/contacts/group")}>New group</button><div style={{ height: 20 }} />{contacts.map(contact => <button className="card" key={contact.id} style={{ width: "100%", display: "flex", alignItems: "center", gap: 12, textAlign: "left" }} onClick={() => router.push(`/contacts/${contact.id}`)}><Avatar name={contact.name} /><span style={{ flex: 1 }}><strong>{contact.is_favorite ? "★ " : ""}{contact.name}</strong><small style={{ display: "block", color: "var(--muted)" }}>{contact.email || contact.phone_number || "No email"} · {contact.is_blocked ? "Blocked" : contact.linked_user ? "On MyChat" : "Not linked yet"}</small></span><ChevronRight size={17} /></button>)}{contacts.length === 0 && <p className="sub">No contacts yet. Add a friend using their registered MyChat email.</p>}</>}
  </div></main>;
}

function StatusPanel({ stories, path, me }: { stories: Story[]; path: string; me: User }) {
  const router = useRouter(); const queryClient = useQueryClient(); const [body, setBody] = useState(""); const [background, setBackground] = useState("#128C7E"); const [media, setMedia] = useState<File | null>(null); const [error, setError] = useState("");
  const selected = stories.find(s => s.id === path.split("/")[2]);
  const create = useMutation({ mutationFn: () => { const data = new FormData(); data.append("body", body); data.append("background", background); if (media) data.append("media", media); return api<Story>("/stories/", { method: "POST", body: data }); }, onSuccess: s => { queryClient.invalidateQueries({ queryKey: ["stories"] }); router.push(`/status/${s.id}`); }, onError: (e: Error) => setError(e.message) });
  useEffect(() => { if (selected && selected.author.id !== me.id) api(`/stories/${selected.id}/view/`, { method: "POST", body: "{}" }).catch(() => {}); }, [selected?.id]);
  return <main className="workspace"><div className="panel-page"><h1>{path.endsWith("/create") ? "Create a status" : selected ? selected.author.display_name + "’s status" : "Status"}</h1><p className="sub">Moments shared on MyChat disappear after 24 hours.</p>{error && <div className="auth-error">{error}</div>}{path.endsWith("/create") ? <div className="card" style={{ maxWidth: 540 }}><div style={{ height: 220, borderRadius: 14, background, color: "white", display: "grid", placeItems: "center", padding: 25, fontSize: 25, textAlign: "center", marginBottom: 20 }}>{body || "Your story preview"}</div><label className="field">Your story<textarea value={body} maxLength={1000} onChange={e => setBody(e.target.value)} /></label><label className="field">Image or video<input type="file" accept="image/*,video/*" onChange={e => setMedia(e.target.files?.[0] || null)} /></label><label className="field">Background color<input type="color" value={background} onChange={e => setBackground(e.target.value)} /></label><button className="primary" disabled={(!body.trim() && !media) || create.isPending} onClick={() => create.mutate()}>Share status</button></div> : selected ? <div className="card" style={{ maxWidth: 540 }}><div style={{ minHeight: 360, borderRadius: 14, background: selected.background, color: "white", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", padding: 32, textAlign: "center", fontSize: 26 }}>{selected.media_url && (selected.media_type?.startsWith("video/") ? <video src={selected.media_url} controls style={{ maxWidth: "100%", maxHeight: 320 }} /> : <img src={selected.media_url} alt="Story media" style={{ maxWidth: "100%", maxHeight: 320, objectFit: "contain" }} />)}{selected.body}</div><p className="sub" style={{ marginTop: 12 }}>Expires {format(new Date(selected.expires_at), "PPp")} · {selected.view_count} views</p>{selected.author.id === me.id && <button className="secondary danger" onClick={async () => { if (!window.confirm("Delete this status?")) return; try { await api(`/stories/${selected.id}/`, { method: "DELETE" }); queryClient.invalidateQueries({ queryKey: ["stories"] }); router.push("/status"); } catch (cause) { setError((cause as Error).message); } }}>Delete status</button>}</div> : <><button className="primary" onClick={() => router.push("/status/create")}>Create a status</button><div style={{ height: 20 }} />{stories.map(s => <button className="card" key={s.id} style={{ width: "100%", display: "flex", alignItems: "center", gap: 12, textAlign: "left" }} onClick={() => router.push(`/status/${s.id}`)}><Avatar name={s.author.display_name} /><span style={{ flex: 1 }}><strong>{s.author.display_name}</strong><small style={{ display: "block", color: "var(--muted)" }}>{format(new Date(s.created_at), "PPp")} · {s.body.slice(0, 60)}</small></span><ChevronRight size={17} /></button>)}{stories.length === 0 && <p className="sub">No active stories. Share the first one.</p>}</>}</div></main>;
}

function SettingsPanel({ path, me }: { path: string; me: User }) {
  const router = useRouter(); const queryClient = useQueryClient(); const [name, setName] = useState(me.display_name); const [bio, setBio] = useState(me.bio); const [error, setError] = useState(""); const [success, setSuccess] = useState("");
  const prefs = useQuery({ queryKey: ["preferences"], queryFn: () => api<{ theme: string; notifications: boolean; read_receipts: boolean; enter_to_send: boolean }>("/users/me/preferences/") });
  const whatsapp = useQuery({ queryKey: ["whatsapp-status"], queryFn: () => api<{ configured: boolean; connection_state: string; phone_number: string; phone_number_id: string; business_account_id: string; last_webhook_at: string | null }>("/integrations/whatsapp/status/"), enabled: path.includes("whatsapp") });
  const saveProfile = async () => { try { await api("/users/me/", { method: "PATCH", body: JSON.stringify({ display_name: name, bio }) }); queryClient.invalidateQueries({ queryKey: ["me"] }); setError(""); setSuccess("Profile saved."); } catch (cause) { setSuccess(""); setError((cause as Error).message); } };
  const updatePref = async (key: string, value: string | boolean) => {
    try {
      await api("/users/me/preferences/", { method: "PATCH", body: JSON.stringify({ [key]: value }) });
      queryClient.invalidateQueries({ queryKey: ["preferences"] });
      if (key === "theme") document.documentElement.dataset.theme = value === "system" ? "" : String(value);
      setError(""); setSuccess("Preference saved.");
      return true;
    } catch (cause) { setSuccess(""); setError((cause as Error).message); return false; }
  };
  const logout = async () => { try { await api("/auth/logout/", { method: "POST", body: "{}" }); queryClient.clear(); router.push("/login"); } catch (cause) { setError((cause as Error).message); } };
  const enableNotifications = async () => {
    if (!("Notification" in window)) { setError("This browser does not support notifications."); return; }
    const permission = await Notification.requestPermission();
    if (permission === "granted") { if (await updatePref("notifications", true)) setSuccess("Browser notifications enabled."); }
    else setError("Browser notification permission was not granted.");
  };
  return <main className="workspace"><div className="panel-page"><h1>Settings</h1><p className="sub">Make MyChat feel like yours.</p>{error && <div className="auth-error">{error}</div>}{success && <div style={{ color: "var(--accent-dark)", fontSize: 13, marginBottom: 15 }}>{success}</div>}<div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 24 }}>{[{ href: "/settings/profile", label: "Profile" }, { href: "/settings/appearance", label: "Appearance" }, { href: "/settings/notifications", label: "Notifications" }, { href: "/settings/chat", label: "Chat" }, { href: "/settings/privacy", label: "Privacy" }, { href: "/settings/integrations/whatsapp", label: "WhatsApp" }].map(t => <Link key={t.href} className="secondary" style={{ textDecoration: "none", borderColor: path === t.href ? "var(--accent)" : "var(--line)" }} href={t.href}>{t.label}</Link>)}</div>{path.includes("whatsapp") ? <div className="card" style={{ maxWidth: 580 }}><h3>WhatsApp Business Cloud API</h3><p className="sub">Official Meta Business connection. Personal WhatsApp chats and Status are unavailable here.</p><div className="info-row"><span className={`provider-pill ${whatsapp.data?.configured ? "" : "whatsapp"}`}>{whatsapp.data?.configured ? "Configured · live status unverified" : "Disconnected"}</span></div><div className="info-row">Business number: {whatsapp.data?.phone_number || "Not configured"}</div><div className="info-row">Phone number ID: {whatsapp.data?.phone_number_id || "—"}</div><div className="info-row">Last webhook: {whatsapp.data?.last_webhook_at ? format(new Date(whatsapp.data.last_webhook_at), "PPp") : "Never"}</div><p style={{ fontSize: 12, color: "var(--muted)" }}>Connect through Meta Business setup, then configure server secrets and the account in Django Admin.</p></div> : path.includes("appearance") ? <div className="card" style={{ maxWidth: 580 }}><h3>Appearance</h3><label className="field">Theme<select value={prefs.data?.theme || "system"} onChange={e => updatePref("theme", e.target.value)}><option value="system">System</option><option value="light">Light</option><option value="dark">Dark</option></select></label></div> : path.includes("notifications") ? <div className="card" style={{ maxWidth: 580 }}><h3>Notifications</h3><label className="info-row"><input type="checkbox" checked={prefs.data?.notifications || false} onChange={e => updatePref("notifications", e.target.checked)} /> Enable notifications</label><p className="sub">Alerts appear when this tab is in the background and your browser has permission.</p><button className="secondary" onClick={enableNotifications}>Allow browser alerts</button></div> : path.includes("chat") ? <div className="card" style={{ maxWidth: 580 }}><h3>Chat</h3><label className="info-row"><input type="checkbox" checked={prefs.data?.enter_to_send ?? true} onChange={e => updatePref("enter_to_send", e.target.checked)} /> Press Enter to send messages</label></div> : path.includes("privacy") ? <div className="card" style={{ maxWidth: 580 }}><h3>Privacy</h3><label className="info-row"><input type="checkbox" checked={prefs.data?.read_receipts || false} onChange={e => updatePref("read_receipts", e.target.checked)} /> Send read receipts for internal chats</label></div> : <div className="card" style={{ maxWidth: 580 }}><div style={{ display: "flex", gap: 14, alignItems: "center", marginBottom: 24 }}><Avatar name={me.display_name} size={62} /><div><strong>{me.display_name}</strong><div style={{ fontSize: 12, color: "var(--muted)" }}>{me.email}</div></div></div><label className="field">Display name<input value={name} onChange={e => setName(e.target.value)} /></label><label className="field">About<textarea value={bio} onChange={e => setBio(e.target.value)} /></label><button className="primary" onClick={saveProfile}>Save profile</button><button className="secondary" style={{ marginLeft: 8 }} onClick={logout}><LogOut size={14} style={{ display: "inline" }} /> Log out</button></div>}</div></main>;
}
