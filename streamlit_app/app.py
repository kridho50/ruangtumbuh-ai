import json
import os
import re
import sqlite3
import urllib.parse
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

APP_DIR = Path(__file__).resolve().parent
for env_file in (APP_DIR / ".env.local", APP_DIR.parent / ".env.local"):
    if env_file.exists():
        load_dotenv(env_file)
        break

DB_PATH = APP_DIR / "chat_history.db"
MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
API_KEY = os.getenv("GEMINI_API_KEY", "")

SUBJECTS = ["Pemrograman", "Sains", "Matematika", "Bahasa Inggris", "Umum"]
SUBJECT_HINTS = {
    "Pemrograman": "berfokus pada pemrograman dan ilmu komputer",
    "Sains": "berfokus pada sains (fisika, kimia, biologi) dan pengetahuan alam",
    "Matematika": "berfokus pada matematika dan logika berpikir",
    "Bahasa Inggris": "berfokus pada pembelajaran Bahasa Inggris (kosakata, tata bahasa, percakapan)",
    "Umum": "mencakup topik pembelajaran umum sesuai pertanyaan pengguna",
}
STOPWORDS = {
    "apa", "itu", "ini", "yang", "adalah", "ialah", "sebagai", "dengan", "untuk", "dari", "pada", "dalam",
    "ke", "di", "dan", "atau", "jelaskan", "jelaskanlah", "buat", "buatlah", "buatkan", "berikan", "berikanlah",
    "tolong", "dong", "tentang", "bagaimana", "mengapa", "kenapa", "kapan", "dimana", "mana", "siapa", "berapa",
    "bisa", "ada", "punya", "aku", "saya", "kita", "kamu", "anda", "mereka", "agar", "supaya", "kalau", "jika",
    "bila", "perlu", "ingin", "mau", "sih", "kah", "nggak", "tidak", "tak", "the", "a", "an", "is", "are", "what",
    "how", "why", "when", "who", "where", "explain", "make", "create",
}
WIKIPEDIA_HEADERS = {
    "User-Agent": "RuangTumbuhAI/1.0 (chatbot mentor belajar berbahasa Indonesia)",
    "Api-User-Agent": "RuangTumbuhAI/1.0 (chatbot mentor belajar berbahasa Indonesia)",
}


def now_text() -> str:
    return datetime.now().isoformat(timespec="seconds")


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            created_at TEXT NOT NULL
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
            role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
            content TEXT NOT NULL,
            references_json TEXT,
            created_at TEXT NOT NULL
        )"""
    )
    conn.commit()
    return conn


def create_session() -> str:
    session_id = uuid.uuid4().hex[:12]
    conn = get_conn()
    try:
        conn.execute("INSERT INTO sessions (id, title, created_at) VALUES (?, ?, ?)", (session_id, "Percakapan baru", now_text()))
        conn.commit()
    finally:
        conn.close()
    return session_id


def get_latest_session() -> sqlite3.Row | None:
    conn = get_conn()
    try:
        return conn.execute(
            """SELECT s.* FROM sessions s
               WHERE EXISTS (SELECT 1 FROM messages m WHERE m.session_id = s.id)
               ORDER BY s.created_at DESC, s.rowid DESC LIMIT 1"""
        ).fetchone()
    finally:
        conn.close()


def list_sessions(limit: int = 8) -> list[sqlite3.Row]:
    conn = get_conn()
    try:
        return conn.execute(
            """SELECT s.id, s.title, s.created_at, COUNT(m.id) AS total
               FROM sessions s JOIN messages m ON m.session_id = s.id
               GROUP BY s.id ORDER BY MAX(m.id) DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    finally:
        conn.close()


def load_messages(session_id: str) -> list[dict]:
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT role, content, references_json FROM messages WHERE session_id = ? ORDER BY id",
            (session_id,),
        ).fetchall()
    finally:
        conn.close()
    return [
        {
            "role": row["role"],
            "content": row["content"],
            "references": json.loads(row["references_json"] or "[]"),
        }
        for row in rows
    ]


def save_message(session_id: str, role: str, content: str, references: list[dict]) -> None:
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO messages (session_id, role, content, references_json, created_at) VALUES (?, ?, ?, ?, ?)",
            (session_id, role, content, json.dumps(references, ensure_ascii=False), now_text()),
        )
        conn.commit()
    finally:
        conn.close()


def set_session_title(session_id: str, title: str) -> None:
    conn = get_conn()
    try:
        conn.execute("UPDATE sessions SET title = ? WHERE id = ?", (title[:60], session_id))
        conn.commit()
    finally:
        conn.close()


def delete_session(session_id: str) -> None:
    conn = get_conn()
    try:
        conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        conn.commit()
    finally:
        conn.close()


def _wiki_json(url: str) -> dict:
    request = urllib.request.Request(url, headers=WIKIPEDIA_HEADERS)
    with urllib.request.urlopen(request, timeout=8) as response:
        return json.loads(response.read().decode("utf-8"))


def _search_wikipedia(query: str) -> list[str]:
    url = "https://id.wikipedia.org/w/api.php?" + urllib.parse.urlencode(
        {"action": "query", "list": "search", "srlimit": 3, "format": "json", "srsearch": query}
    )
    data = _wiki_json(url)
    hits = data.get("query", {}).get("search", [])
    return [hit["title"] for hit in hits if hit.get("title")]


def _is_relevant_title(title: str, terms: list[str]) -> bool:
    lowered = title.lower()
    if any(len(term) >= 4 and term in lowered for term in terms):
        return True
    title_words = [word for word in re.split(r"[^\w]+", lowered) if len(word) >= 4]
    return any(word in term for word in title_words for term in terms)


def extract_search_terms(question: str) -> list[str]:
    words = [word.strip(".,!?;:()[]\"'").lower() for word in question.split()]
    terms = [word for word in words if len(word) > 1 and word.replace("-", "").isalnum() and word not in STOPWORDS]
    return list(dict.fromkeys(terms))


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_wikipedia_reference(question: str) -> dict | None:
    try:
        cleaned = " ".join(question.split())[:80]
        if not cleaned:
            return None
        terms = extract_search_terms(question)
        candidates = _search_wikipedia(cleaned)
        if terms:
            candidates += _search_wikipedia(" ".join(terms))
        title = next((candidate for candidate in candidates if _is_relevant_title(candidate, terms)), None)
        if not title:
            return None
        summary = _wiki_json(f"https://id.wikipedia.org/api/rest_v1/page/summary/{urllib.parse.quote(title)}")
        url = summary.get("content_urls", {}).get("desktop", {}).get("page")
        extract = summary.get("extract")
        if not url or not extract:
            return None
        return {"title": summary.get("title", title), "url": url, "summary": extract[:300]}
    except Exception:
        return None


def cari_wikipedia(topik: str) -> str:
    """Ambil ringkasan topik dari Wikipedia bahasa Indonesia beserta URL sumbernya.

    Args:
        topik: 1-3 kata kunci spesifik, misalnya "fotosintesis" atau "closure JavaScript".
    """
    reference = fetch_wikipedia_reference(topik)
    if not reference:
        return f"Tidak ditemukan artikel Wikipedia yang relevan untuk '{topik}'."
    return f"{reference['title']}: {reference['summary']} (Sumber: {reference['url']})"


def demo_answer(question: str, subject: str, tone: str) -> str:
    friendly = "" if tone == "formal" else "Kita buat sederhana, ya. "
    lower = question.lower()
    if "closure" in lower:
        return (
            f"{friendly}Closure adalah fungsi yang tetap mengingat variabel dari tempat ia dibuat, "
            "bahkan setelah fungsi luarnya selesai dijalankan.\n\n"
            "```python\n"
            "def buat_penghitung():\n"
            "    nilai = 0\n"
            "    def tambah():\n"
            "        nonlocal nilai\n"
            "        nilai += 1\n"
            "        return nilai\n"
            "    return tambah\n"
            "```\n\n"
            "Fungsi `tambah` tetap punya akses ke `nilai`. Coba tebak hasil jika dipanggil tiga kali."
        )
    if "7 hari" in lower or "rencana" in lower:
        return (
            f"{friendly}Rencana 7 hari untuk {subject}:\n\n"
            "1. Peta konsep: tulis yang sudah kamu kuasai\n"
            "2. Konsep inti hari ini (30 menit teori)\n"
            "3. Latihan terpandu\n"
            "4. Latihan mandiri + cek jawaban\n"
            "5. Proyek mini sederhana\n"
            "6. Review dan perbaiki kelemahan\n"
            "7. Simulasi + refleksi\n\n"
            "Targetkan 45 menit per hari: 15 menit teori, 20 menit praktik, 10 menit rangkuman."
        )
    if "latihan" in lower:
        return (
            f"{friendly}Latihan singkat: buat fungsi `hitung_genap` yang menerima list angka "
            "dan mengembalikan jumlah bilangan genap.\n\n"
            "Contoh input: [1, 2, 4, 7, 8]\nHasil yang diharapkan: 3\n\n"
            "Kirim jawabanmu dan aku akan memberi umpan balik."
        )
    return (
        f"{friendly}Aku menangkap bahwa kamu ingin mempelajari: \"{question}\". "
        "Mulailah dengan menuliskan apa yang sudah kamu pahami dalam satu kalimat. "
        "Setelah itu, kita pecah konsepnya menjadi definisi, contoh, lalu latihan kecil.\n\n"
        "Mode demo lokal sedang aktif, jadi ini jawaban contoh. Tambahkan GEMINI_API_KEY "
        "(dan kuota yang tersedia) untuk jawaban AI dinamis."
    )


def suggest_next_steps(topic: str) -> list[str]:
    lower = topic.lower()
    if "closure" in lower or "fungsi" in lower:
        return ["Apa beda closure dan scope?", "Latihan: buat counter dengan closure", "Apa itu higher-order function?"]
    if "rencana" in lower:
        return ["Evaluasi progres rencana belajarku", "Buatkan latihan untuk hari pertama", "Tips konsisten belajar 7 hari"]
    if "latihan" in lower:
        return ["Minta latihan yang lebih menantang", "Periksa jawaban latihanku", "Rangkum materi latihan ini"]
    return ["Buatkan rencana belajar 7 hari untuk topik ini", "Jelaskan konsep intinya secara sederhana", "Beri aku latihan singkat"]


def build_system_instruction(subject: str, tone: str) -> str:
    return (
        f"Kamu adalah Ruang AI, mentor belajar personal berbahasa Indonesia yang {SUBJECT_HINTS[subject]}. "
        f"Gunakan gaya {tone}. Terapkan metode Jelaskan-Contohkan-Latih: jelaskan inti secara runtut, "
        "beri contoh konkret bila relevan, lalu tutup dengan pertanyaan refleksi atau latihan singkat. "
        "Batasi jawaban maksimal sekitar 300 kata. Kamu punya tool cari_wikipedia; panggil tool itu "
        "ketika butuh fakta atau referensi yang bisa diverifikasi. Jangan mengarang fakta. Bila tidak yakin, "
        "katakan keterbatasanmu. Jangan memberikan klaim medis, hukum, atau finansial sebagai nasihat profesional."
    )


def generate_with_gemini(subject: str, tone: str, temperature: float, messages: list[dict]) -> str:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=API_KEY)
    history = [
        types.Content(
            role="user" if message["role"] == "user" else "model",
            parts=[types.Part.from_text(text=message["content"])],
        )
        for message in messages[:-1][-19:]
    ]
    config = types.GenerateContentConfig(
        system_instruction=build_system_instruction(subject, tone),
        temperature=temperature,
        top_p=0.9,
        max_output_tokens=2048,
        tools=[cari_wikipedia],
    )
    chat = client.chats.create(model=MODEL, config=config, history=history)
    response = chat.send_message(messages[-1]["content"])
    text = (response.text or "").strip()
    if not text:
        raise RuntimeError("Gemini mengembalikan respons kosong.")
    return text


def answer(question: str, subject: str, tone: str, temperature: float, messages: list[dict], demo_mode: bool) -> tuple[str, str, str | None]:
    if demo_mode or not API_KEY:
        note = None if demo_mode else "GEMINI_API_KEY belum diisi, jadi mode demo lokal otomatis aktif."
        return demo_answer(question, subject, tone), "demo", note
    try:
        return generate_with_gemini(subject, tone, temperature, messages), "gemini", None
    except Exception as error:
        print(f"[Ruang AI] Gemini tidak tersedia: {error}")
        return demo_answer(question, subject, tone), "demo", "Gemini sedang tidak tersedia (mis. kuota habis). Jawaban ini dari mode demo lokal."


def render_reference(reference: dict) -> None:
    with st.container(border=True):
        st.caption("REFERENSI EKSTERNAL · WIKIPEDIA")
        st.markdown(f"**{reference['title']}**")
        st.write(reference["summary"])
        st.link_button("Baca di Wikipedia", reference["url"], width="stretch")


def init_state() -> None:
    if "session_id" in st.session_state:
        return
    latest = get_latest_session()
    if latest:
        st.session_state.session_id = latest["id"]
        st.session_state.messages = load_messages(latest["id"])
    else:
        st.session_state.session_id = create_session()
        st.session_state.messages = []
    st.session_state.suggestions = []


def handle_prompt(prompt: str, subject: str, tone: str, temperature: float, demo_mode: bool) -> None:
    session_id = st.session_state.session_id
    if not st.session_state.messages:
        set_session_title(session_id, prompt)

    st.session_state.messages.append({"role": "user", "content": prompt, "references": []})
    save_message(session_id, "user", prompt, [])
    st.session_state.suggestions = []

    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Ruang AI sedang menyusun jawaban..."):
            result, mode, note = answer(prompt, subject, tone, temperature, st.session_state.messages, demo_mode)
            reference = fetch_wikipedia_reference(prompt)
        st.markdown(result)
        references = [reference] if reference else []
        for item in references:
            render_reference(item)
        if note:
            st.caption(f"Mode demo: {note}")
        if mode == "gemini":
            st.caption(f"Model: {MODEL} · temperature {temperature:.1f}")

    st.session_state.messages.append({"role": "assistant", "content": result, "references": references})
    save_message(session_id, "assistant", result, references)
    last_prompt = prompt.strip().lower()
    st.session_state.suggestions = [s for s in suggest_next_steps(prompt) if s.lower() != last_prompt]
    st.rerun()


st.set_page_config(page_title="Ruang AI - Mentor Belajar", layout="centered")
init_state()

with st.sidebar:
    st.subheader("RuangTumbuh AI")
    st.caption("Ruang AI - mentor belajar personal. Gemini + Streamlit + SQLite.")
    st.divider()
    st.markdown("**Personalisasi**")
    subject = st.selectbox("Domain materi", SUBJECTS)
    tone_label = st.radio("Gaya bahasa", ["Santai", "Formal"], horizontal=True)
    tone = "formal" if tone_label == "Formal" else "santai"
    temperature = st.slider("Kreativitas (temperature)", 0.0, 1.0, 0.7, 0.1)
    demo_mode = st.toggle(
        "Mode demo lokal",
        value=not API_KEY,
        help="Menjawab tanpa memanggil Gemini - hemat kuota dan tetap bisa didemokan.",
    )
    st.divider()
    st.markdown("**Riwayat chat**")
    if st.button("+ Percakapan baru", width="stretch", type="primary"):
        st.session_state.session_id = create_session()
        st.session_state.messages = []
        st.session_state.suggestions = []
        st.rerun()
    for row in list_sessions():
        active = row["id"] == st.session_state.session_id
        label = f"{'● ' if active else ''}{row['title']} ({row['total']})"
        if st.button(label, key=f"session-{row['id']}", width="stretch", type="primary" if active else "secondary"):
            st.session_state.session_id = row["id"]
            st.session_state.messages = load_messages(row["id"])
            st.session_state.suggestions = []
            st.rerun()
    if st.button("Hapus percakapan ini", width="stretch"):
        delete_session(st.session_state.session_id)
        latest = get_latest_session()
        st.session_state.session_id = latest["id"] if latest else create_session()
        st.session_state.messages = load_messages(st.session_state.session_id)
        st.session_state.suggestions = []
        st.rerun()
    st.divider()
    st.caption(f"Model: `{MODEL}`")
    st.caption(f"Penyimpanan: `{DB_PATH.name}` (SQLite)")

st.title("Halo, siap bertumbuh hari ini?")
st.caption("Mentor belajar personal dengan referensi Wikipedia, memory SQLite, dan rekomendasi lanjutan.")

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        for reference in message.get("references", []):
            render_reference(reference)

if st.session_state.suggestions:
    st.caption("Rekomendasi lanjutan")
    suggestion_columns = st.columns(len(st.session_state.suggestions))
    for column, suggestion in zip(suggestion_columns, st.session_state.suggestions):
        if column.button(suggestion, key=f"suggestion-{suggestion}", width="stretch"):
            st.session_state.pending_prompt = suggestion
            st.rerun()

pending_prompt = st.session_state.pop("pending_prompt", None)
user_prompt = st.chat_input("Tanyakan apa saja tentang materi belajarmu...") or pending_prompt
if user_prompt:
    handle_prompt(user_prompt, subject, tone, temperature, demo_mode)
