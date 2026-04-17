import { NextResponse } from 'next/server';

const BOT_URL = process.env.PYTHON_BOT_URL || 'http://localhost:8000';

export async function GET() {
  try {
    const res = await fetch(`${BOT_URL}/price`, { cache: 'no-store' });
    const data = await res.json();
    return NextResponse.json(data);
  } catch {
    return NextResponse.json(
      { price: 0, connected: false, error: 'Bot server not reachable' },
      { status: 503 }
    );
  }
}
