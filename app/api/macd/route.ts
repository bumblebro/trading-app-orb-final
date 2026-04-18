import { NextResponse } from 'next/server';

const BOT_URL = process.env.PYTHON_BOT_URL || 'http://localhost:8000';

export async function GET() {
  try {
    const res = await fetch(`${BOT_URL}/macd`, { cache: 'no-store' });
    const data = await res.json();
    return NextResponse.json(data);
  } catch {
    return NextResponse.json({ macd_line: 0, signal_line: 0, histogram: 0, is_bullish: false, is_curling_up: false, is_curling_down: false }, { status: 503 });
  }
}
