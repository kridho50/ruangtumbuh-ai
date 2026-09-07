type Role = 'user' | 'model';
type Message = { role: Role; text: string };

const MODEL = process.env.GEMINI_MODEL || 'gemini-2.5-flash';

function isMessage(value: unknown): value is Message {
  if (!value || typeof value !== 'object') return false;
  const item = value as Record<string, unknown>;
  return (item.role === 'user' || item.role === 'model') && typeof item.text === 'string' && item.text.trim().length > 0 && item.text.length <= 4000;
}

function demoResponse(question: string, tone: string) {
  const friendly = tone === 'formal' ? '' : 'Kita buat sederhana, ya. ';
  const lower = question.toLowerCase();
  if (lower.includes('closure')) {
    return `${friendly}Closure adalah fungsi yang tetap “mengingat” variabel dari tempat ia dibuat, bahkan setelah fungsi luarnya selesai dijalankan.\n\nContoh:\nfunction buatPenghitung() {\n  let nilai = 0;\n  return () => ++nilai;\n}\n\nFungsi yang dikembalikan tetap punya akses ke nilai. Coba tebak hasil jika fungsi itu dipanggil tiga kali berturut-turut.`;
  }
  if (lower.includes('7 hari') || lower.includes('rencana')) {
    return `${friendly}Rencana 7 hari JavaScript:\n\n1. Variabel dan tipe data\n2. Kondisi dan perulangan\n3. Fungsi dan scope\n4. Array dan object\n5. DOM dan event\n6. Fetch API\n7. Mini project + refleksi\n\nTargetkan 45 menit per hari: 15 menit teori, 20 menit praktik, dan 10 menit rangkuman.`;
  }
  if (lower.includes('latihan')) {
    return `${friendly}Latihan singkat: buat fungsi bernama hitungGenap yang menerima array angka dan mengembalikan jumlah bilangan genap di dalamnya.\n\nContoh input: [1, 2, 4, 7, 8]\nHasil yang diharapkan: 3\n\nKirim jawabanmu dan aku akan memberi umpan balik.`;
  }
  return `${friendly}Aku menangkap bahwa kamu ingin mempelajari: “${question}”. Mulailah dengan menuliskan apa yang sudah kamu pahami dalam satu kalimat. Setelah itu, kita pecah konsepnya menjadi definisi, contoh, lalu latihan kecil.\n\nMode demo sedang aktif. Tambahkan GEMINI_API_KEY untuk mendapatkan jawaban AI dinamis.`;
}

export async function GET() {
  return Response.json({
    mode: process.env.GEMINI_API_KEY ? 'gemini' : 'demo',
    model: process.env.GEMINI_API_KEY ? MODEL : null,
  });
}

export async function POST(request: Request) {
  try {
    const body = await request.json() as Record<string, unknown>;
    const messages = Array.isArray(body.messages) ? body.messages.filter(isMessage).slice(-20) : [];
    const tone = body.tone === 'formal' ? 'formal' : 'santai';
    const temperature = Math.min(1, Math.max(0, typeof body.temperature === 'number' ? body.temperature : 0.7));
    const subject = typeof body.subject === 'string' ? body.subject.slice(0, 80) : 'pembelajaran umum';
    if (!messages.length) return Response.json({ error: 'Percakapan wajib berisi setidaknya satu pesan.' }, { status: 400 });

    const apiKey = process.env.GEMINI_API_KEY;
    const lastQuestion = [...messages].reverse().find((message) => message.role === 'user')?.text || '';
    if (!apiKey) return Response.json({ result: demoResponse(lastQuestion, tone), mode: 'demo' });

    const systemInstruction = `Kamu adalah Alisha, mentor belajar personal berbahasa Indonesia untuk domain ${subject}. Gunakan gaya ${tone}. Terapkan metode Jelaskan-Contohkan-Latih: jelaskan inti secara runtut, beri contoh konkret bila relevan, lalu tutup dengan pertanyaan refleksi atau latihan singkat. Jangan mengarang fakta. Bila tidak yakin, katakan keterbatasanmu. Hindari jawaban bertele-tele dan jangan memberikan klaim medis, hukum, atau finansial sebagai nasihat profesional.`;
    const response = await fetch(`https://generativelanguage.googleapis.com/v1beta/models/${MODEL}:generateContent?key=${encodeURIComponent(apiKey)}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        system_instruction: { parts: [{ text: systemInstruction }] },
        contents: messages.map((message) => ({ role: message.role, parts: [{ text: message.text }] })),
        generationConfig: { temperature, topP: 0.9, topK: 40, maxOutputTokens: 900 },
      }),
    });
    const data = await response.json() as { candidates?: Array<{ content?: { parts?: Array<{ text?: string }> } }>; error?: { message?: string } };
    if (!response.ok) throw new Error(data.error?.message || 'Gemini API tidak dapat memproses permintaan.');
    const result = data.candidates?.[0]?.content?.parts?.map((part) => part.text || '').join('').trim();
    if (!result) throw new Error('Gemini mengembalikan respons kosong.');
    return Response.json({ result, mode: 'gemini' });
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Kesalahan server tidak diketahui.';
    return Response.json({ error: message }, { status: 500 });
  }
}
