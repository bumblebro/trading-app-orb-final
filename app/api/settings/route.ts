import { NextRequest, NextResponse } from 'next/server';

const BOT_URL = process.env.PYTHON_BOT_URL || 'http://localhost:8000';

export async function GET() {
  const url = `${BOT_URL}/settings`;
  try {
    const res = await fetch(url, { cache: 'no-store', signal: AbortSignal.timeout(5000) });
    if (!res.ok) {
      const errBody = await res.text();
      return NextResponse.json({ settings: {}, error: `Bot ${res.status}: ${errBody}` }, { status: 503 });
    }
    const data = await res.json();
    return NextResponse.json(data, {
      headers: { 'Cache-Control': 'no-store, no-cache, must-revalidate' }
    });
  } catch (e: any) {
    return NextResponse.json({ settings: {}, error: e?.message }, { status: 503 });
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
