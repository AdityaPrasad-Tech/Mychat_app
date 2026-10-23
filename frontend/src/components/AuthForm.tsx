"use client";
import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { ArrowRight, LockKeyhole, MessageCircle } from "lucide-react";
import { api } from "@/lib/api";

export default function AuthForm({ mode }: { mode: "login" | "register" }) {
  const router = useRouter(); const queryClient = useQueryClient();
  const [email, setEmail] = useState(""); const [password, setPassword] = useState(""); const [name, setName] = useState(""); const [error, setError] = useState(""); const [loading, setLoading] = useState(false);
  const submit = async (event: React.FormEvent) => {
    event.preventDefault(); setError(""); setLoading(true);
    try { await api(`/auth/${mode}/`, { method: "POST", body: JSON.stringify(mode === "register" ? { email, password, display_name: name } : { email, password }) }); queryClient.invalidateQueries({ queryKey: ["me"] }); router.push("/chats"); }
    catch (err) { setError((err as Error).message); }
    finally { setLoading(false); }
  };
  return <div className="auth-screen"><div className="auth-art"><div className="auth-art-inner"><div className="brand-mark" style={{ width: 58, height: 58, fontSize: 29 }}>m</div><h1>Every connection starts with a hello.</h1><p>One calm space for your conversations, groups, and moments. Stay close to what matters.</p><div style={{ display: "flex", gap: 10, marginTop: 45, alignItems: "center", color: "#d3eadf" }}><MessageCircle size={18} /> Built for meaningful conversations</div></div></div><div className="auth-form-wrap"><form className="auth-form" onSubmit={submit}><div style={{ color: "var(--accent)", fontWeight: 800, marginBottom: 32 }}>mychat.</div><h2>{mode === "login" ? "Welcome back" : "Create your account"}</h2><p>{mode === "login" ? "Enter your details to continue your conversations." : "Join MyChat and make room for good conversations."}</p>{error && <div className="auth-error" role="alert">{error}</div>}{mode === "register" && <label className="field">Your name<input value={name} onChange={e => setName(e.target.value)} required autoComplete="name" /></label>}<label className="field">Email address<input type="email" value={email} onChange={e => setEmail(e.target.value)} required autoComplete="email" /></label><label className="field">Password<input type="password" value={password} onChange={e => setPassword(e.target.value)} required minLength={10} autoComplete={mode === "login" ? "current-password" : "new-password"} /></label><button className="primary" disabled={loading} style={{ width: "100%", marginTop: 6, padding: 14 }}>{loading ? "Please wait…" : mode === "login" ? "Sign in" : "Create account"} <ArrowRight size={16} style={{ display: "inline", marginLeft: 5 }} /></button><p style={{ marginTop: 25, fontSize: 13, textAlign: "center" }}>{mode === "login" ? "New to MyChat? " : "Already have an account? "}<Link className="text-link" href={mode === "login" ? "/register" : "/login"}>{mode === "login" ? "Create an account" : "Sign in"}</Link></p><div style={{ display: "flex", alignItems: "center", gap: 6, color: "var(--muted)", fontSize: 11, marginTop: 50 }}><LockKeyhole size={13} /> Your messages are stored securely on MyChat servers.</div></form></div></div>;
}
