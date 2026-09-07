'use client';

import { KeyboardEvent, SyntheticEvent, useCallback, useEffect, useRef, useState } from 'react';
import {
  ArrowUp, BookOpen, Lightbulb, Plus, Sparkles, Target,
} from 'lucide-react';

type Role = 'user' | 'model';
type ChatMessage = { role: Role; text: string };
type Tone = 'santai' | 'formal';

declare global {
  interface Document {
    modelContext?: {
      registerTool: (tool: Record<string, unknown>, options?: { signal?: AbortSignal }) => void | Promise<void>;
    };
  }
}

const welcome: ChatMessage = {
  role: 'model',
  text: 'Hai! Aku Alisha. Kita bisa membedah konsep yang membingungkan, membuat rencana belajar, atau latihan soal bareng.\n\nMau mulai dari mana?',
};

function migrateStoredMessages(value: unknown): ChatMessage[] | null {
  if (!Array.isArray(value) || !value.length) return null;

  const messages = value.filter((item): item is ChatMessage => (
    typeof item === 'object'
    && item !== null
    && ((item as ChatMessage).role === 'user' || (item as ChatMessage).role === 'model')
    && typeof (item as ChatMessage).text === 'string'
  ));
  if (!messages.length) return null;

  const [firstMessage, ...rest] = messages;
  if (firstMessage.role === 'model' && /\baku\s+nara\b/i.test(firstMessage.text)) {
    return [welcome, ...rest];
  }

  return messages;
}

const prompts = [
  { icon: BookOpen, text: 'Jelaskan konsep closure' },
  { icon: Target, text: 'Buat rencana belajar 7 hari' },
  { icon: Lightbulb, text: 'Beri aku latihan singkat' },
];

export default function ChatApp() {
  const [messages, setMessages] = useState<ChatMessage[]>([welcome]);
  const [input, setInput] = useState('');
  const [tone, setTone] = useState<Tone>('santai');
  const [temperature, setTemperature] = useState(0.7);
  const [memory, setMemory] = useState(true);
  const [loading, setLoading] = useState(false);
  const [apiMode, setApiMode] = useState<'checking' | 'gemini' | 'demo'>('checking');
  const conversationRef = useRef<HTMLDivElement>(null);
  const storageReadyRef = useRef(false);

  useEffect(() => {
    const saved = localStorage.getItem('ruangtumbuh-chat');
    if (!saved) {
      storageReadyRef.current = true;
      return;
    }
    queueMicrotask(() => {
      try {
        const storedMessages = migrateStoredMessages(JSON.parse(saved));
        if (storedMessages) setMessages(storedMessages);
      } catch { localStorage.removeItem('ruangtumbuh-chat'); }
      finally { storageReadyRef.current = true; }
    });
  }, []);

  useEffect(() => {
    fetch('/api/chat')
      .then((response) => response.json())
      .then((data) => {
        const status = data as { mode?: 'gemini' | 'demo' };
        setApiMode(status.mode === 'gemini' ? 'gemini' : 'demo');
      })
      .catch(() => setApiMode('demo'));
  }, []);

  useEffect(() => {
    if (!storageReadyRef.current) return;
    if (memory) localStorage.setItem('ruangtumbuh-chat', JSON.stringify(messages));
    else localStorage.removeItem('ruangtumbuh-chat');
    conversationRef.current?.scrollTo({ top: conversationRef.current.scrollHeight, behavior: 'smooth' });
  }, [messages, memory, loading]);

  const sendMessage = useCallback(async (rawText: string) => {
    const text = rawText.trim();
    if (!text || loading) return { ok: false, reason: 'Pesan kosong atau respons masih diproses.' };

    const nextMessages = [...messages, { role: 'user' as const, text }];
    setMessages(nextMessages);
    setInput('');
    setLoading(true);

    try {
      const response = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          messages: memory ? nextMessages : [{ role: 'user', text }],
          tone,
          temperature,
          subject: 'Pemrograman',
        }),
      });
      const data = await response.json() as { result?: string; mode?: 'gemini' | 'demo'; error?: string };
      if (!response.ok || !data.result) throw new Error(data.error || 'Respons AI tidak tersedia.');
      const answer = data.result;
      setMessages([...nextMessages, { role: 'model', text: answer }]);
      setApiMode(data.mode || 'gemini');
      return { ok: true, response: data.result, mode: data.mode || 'gemini' };
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Terjadi kesalahan yang tidak diketahui.';
      const failureText = `Maaf, aku belum bisa menjawab. ${message}`;
      setMessages([...nextMessages, { role: 'model', text: failureText }]);
      return { ok: false, reason: message };
    } finally { setLoading(false); }
  }, [loading, memory, messages, temperature, tone]);

  useEffect(() => {
    const context = document.modelContext;
    if (!context?.registerTool) return;
    const lifecycle = new AbortController();
    const tool = {
      name: 'start_learning_chat',
      title: 'Tanya mentor belajar',
      description: 'Kirim pertanyaan belajar ke Alisha dan tampilkan jawabannya dalam percakapan.',
      inputSchema: {
        type: 'object',
        properties: { prompt: { type: 'string', minLength: 1, maxLength: 2000 } },
        required: ['prompt'],
        additionalProperties: false,
      },
      annotations: { readOnlyHint: false, untrustedContentHint: true },
      execute: async (value: unknown) => {
        const prompt = typeof value === 'object' && value !== null && 'prompt' in value
          ? String((value as { prompt: unknown }).prompt).trim() : '';
        if (!prompt || prompt.length > 2000) throw new Error('Prompt harus berisi 1-2000 karakter.');
        return sendMessage(prompt);
      },
    };
    try {
      void Promise.resolve(context.registerTool(tool, { signal: lifecycle.signal })).catch(() => undefined);
    } catch { /* Browser belum mendukung WebMCP. */ }
    return () => lifecycle.abort();
  }, [sendMessage]);

  function handleSubmit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    void sendMessage(input);
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      void sendMessage(input);
    }
  }

  function resetChat() {
    setMessages([welcome]);
    localStorage.removeItem('ruangtumbuh-chat');
  }

  const statusText = apiMode === 'gemini'
    ? 'Gemini 2.5 Flash'
    : apiMode === 'demo' ? 'Mode demo lokal' : 'Memeriksa model';
  const statusLabel = apiMode === 'gemini' ? 'Aktif' : apiMode === 'demo' ? 'Demo' : 'Menghubungkan';

  return (
    <main className="app-shell">
      <header className="topbar">
        <div className="topbar-inner">
          <div className="brand" aria-label="RuangTumbuh AI">
            <span className="brand-mark"><Sparkles size={18} /></span>
            <span>ruangtumbuh<span>.ai</span></span>
          </div>
          <button className="new-chat-inline" type="button" onClick={resetChat}><Plus size={17} /> Chat baru</button>
        </div>
      </header>

      <div className="workspace">
        <section className="chat-panel" id="chat">
          <div className="chat-heading">
            <div>
              <span className="eyebrow">MENTOR BELAJAR PERSONAL</span>
              <h1>Halo, siap bertumbuh hari ini?</h1>
              <output className={`active-model ${apiMode}`} aria-live="polite">
                <span className="status-dot"><i /></span>
                <strong>{statusText}</strong>
                <span className="status-divider" />
                <em>{statusLabel}</em>
              </output>
            </div>
          </div>

          <div className="controls-bar" aria-label="Personalisasi mentor">
            <div className="compact-control tone-control">
              <span>Gaya</span>
              <div className="segmented">
                <button className={tone === 'santai' ? 'selected' : ''} type="button" onClick={() => setTone('santai')}>Santai</button>
                <button className={tone === 'formal' ? 'selected' : ''} type="button" onClick={() => setTone('formal')}>Formal</button>
              </div>
            </div>
            <div className="compact-control creativity-control">
              <label htmlFor="temperature">Kreativitas</label>
              <input id="temperature" type="range" min="0" max="1" step="0.1" value={temperature} onChange={(event) => setTemperature(Number(event.target.value))} />
              <output>{temperature.toFixed(1)}</output>
            </div>
            <div className="compact-control memory-control">
              <span>Memory</span>
              <button className={`toggle ${memory ? 'on' : ''}`} type="button" aria-label={`Memory ${memory ? 'aktif' : 'nonaktif'}`} aria-pressed={memory} onClick={() => setMemory((value) => !value)}><span /></button>
            </div>
          </div>

          <div className="conversation" aria-live="polite" ref={conversationRef}>
            {messages.map((message, index) => (
              <article className={`message ${message.role === 'user' ? 'user-message' : 'mentor-message'}`} key={`${index}-${message.text.slice(0, 16)}`}>
                {message.role === 'model' && <div className="bot-avatar"><Sparkles size={17} /></div>}
                <div>
                  <span className="message-author">{message.role === 'model' ? 'ALISHA · MENTOR AI' : 'KAMU'}</span>
                  <div className="bubble message-text">{message.text}</div>
                </div>
              </article>
            ))}
            {messages.length === 1 && (
              <div className="quick-prompts" aria-label="Contoh pertanyaan">
                {prompts.map(({ icon: Icon, text }) => <button type="button" key={text} onClick={() => void sendMessage(text)}><Icon size={16} /> {text}</button>)}
              </div>
            )}
            {loading && <article className="message mentor-message loading-message"><div className="bot-avatar"><Sparkles size={17} /></div><div><span className="message-author">ALISHA SEDANG MENYUSUN JAWABAN</span><div className="bubble typing"><i /><i /><i /></div></div></article>}
          </div>

          <form className="composer" onSubmit={handleSubmit}>
            <label className="sr-only" htmlFor="message">Tulis pertanyaan</label>
            <textarea id="message" rows={2} maxLength={2000} placeholder="Tanyakan apa saja tentang materi belajarmu..." value={input} onChange={(event) => setInput(event.target.value)} onKeyDown={handleKeyDown} />
            <div className="composer-footer">
              <span><kbd>Shift</kbd> + <kbd>Enter</kbd> untuk baris baru</span>
              <button type="submit" aria-label="Kirim pesan" disabled={!input.trim() || loading}><ArrowUp size={19} /></button>
            </div>
          </form>
          <p className="disclaimer">Alisha dapat membuat kesalahan. Periksa kembali informasi penting.</p>
        </section>
      </div>
    </main>
  );
}
