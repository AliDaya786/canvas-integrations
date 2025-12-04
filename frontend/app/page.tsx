"use client";
import { useState, useEffect } from "react";
import { createClient } from "@supabase/supabase-js";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL;
const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_PROJECT_URL!,
  process.env.NEXT_PUBLIC_SUPABASE_API_KEY!
);

export default function Page() {
  const [name, setName] = useState("");
  const [userId, setUserId] = useState("");
  const [channels, setChannels] = useState<{id: string, name: string}[]>([]);
  const [channelId, setChannelId] = useState("");
  const [messageFormat, setMessageFormat] = useState("");
  const [prompt, setPrompt] = useState("");
  const [aiResult, setAiResult] = useState("");

  useEffect(() => {
    const id = new URLSearchParams(window.location.search).get("user_id");
    if (id) setUserId(id);
  }, []);

  useEffect(() => {
    if (userId) {
      fetch(`${API_BASE}/api/slack_channels?user_id=${userId}`).then(r => r.json()).then(setChannels).catch(() => {});
    }
  }, [userId]);

  async function login() {
    const { data } = await supabase.from("users").select().eq("name", name).single();
    if (!data) {
      await supabase.from("users").insert({ name });
    } else {
      if (data.channel_id) setChannelId(data.channel_id);
      if (data.message_format) setMessageFormat(data.message_format);
    }
    setUserId(name);
  }

  async function connectTool(tool: string) {
    const res = await fetch(`${API_BASE}/api/tool_oauth_start?user_id=${userId}&tool=${tool}`);
    const data = await res.json();
    if (data.redirect_url) window.location.href = data.redirect_url;
  }

  async function saveSettings() {
    await supabase.from("users").update({ channel_id: channelId, message_format: messageFormat }).eq("name", userId);
  }

  async function runAI() {
    setAiResult("Loading...");
    const res = await fetch(`${API_BASE}/api/ai-action`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: userId, prompt: prompt })
    });
    const data = await res.json();
    setAiResult(JSON.stringify(data, null, 2));
  }

  if (!userId) {
    return (
      <main>
        <input value={name} onChange={e => setName(e.target.value)} />
        <button onClick={login}>Login</button>
      </main>
    );
  }

  return (
    <main>
      <button onClick={() => connectTool("slack")}>Connect Slack</button>
      <button onClick={() => connectTool("calendly")}>Connect Calendly</button>
      <button onClick={() => connectTool("attio")}>Connect Attio</button>
      <button onClick={() => connectTool("hubspot")}>Connect Hubspot</button>
      <button onClick={() => connectTool("notion")}>Connect Notion</button>
      <br />
      <select value={channelId} onChange={(e) => setChannelId(e.target.value)}>
        {channels.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
      </select>
      <br />
      <textarea value={messageFormat} onChange={(e) => setMessageFormat(e.target.value)} />
      <br />
      <button onClick={saveSettings}>Save Settings</button>
      <br />
      <br />
      <input
        value={prompt}
        onChange={(e) => setPrompt(e.target.value)}
        placeholder="Enter prompt"
      />
      <button onClick={runAI}>Run AI</button>
      <br />
      <pre>{aiResult}</pre>
    </main>
  );
}
