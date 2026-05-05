import { NextRequest, NextResponse } from 'next/server';

const BOT_URL = process.env.PYTHON_BOT_URL || 'http://localhost:8000';

// DEBUG: remove after testing
export async function HEAD() {
  return NextResponse.json({ bot_url: BOT_URL, will_call: `${BOT_URL}/settings` });
}

export async function GET() {
  const url = `${BOT_URL}/settings`;
  try {
    console.log('[Settings API] Fetching from:', url);
    const res = await fetch(url, { 
      cache: 'no-store',
      signal: AbortSignal.timeout(5000),
    });
    if (!res.ok) {
      const errBody = await res.text();
      return NextResponse.json({ settings: {}, debug_url: url, error: `Bot ${res.status}: ${errBody}` }, { status: 503 });
    }
    const data = await res.json();
    return NextResponse.json({ ...data, debug_url: url }, {
      headers: { 'Cache-Control': 'no-store, no-cache, must-revalidate' }
    });
  } catch (e: any) {
    return NextResponse.json({ settings: {}, debug_url: url, error: e?.message }, { status: 503 });
  }
}

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const res = await fetch(`${BOT_URL}/settings`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    return NextResponse.json(data);
  } catch {
    return NextResponse.json({ error: 'Failed to save settings' }, { status: 503 });
  }
}
