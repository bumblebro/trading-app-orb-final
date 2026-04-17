import { NextResponse } from 'next/server';

const BOT_URL = process.env.PYTHON_BOT_URL || 'http://localhost:8000';

export async function POST() {
  try {
    const res = await fetch(`${BOT_URL}/start`, { method: 'POST', cache: 'no-store' });
    const data = await res.json();
    return NextResponse.json(data);
  } catch {
    return NextResponse.json({ error: 'Bot server not reachable' }, { status: 503 });
  }
}
