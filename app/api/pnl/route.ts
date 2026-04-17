import { NextRequest, NextResponse } from 'next/server';

const BOT_URL = process.env.PYTHON_BOT_URL || 'http://localhost:8000';

export async function GET(request: NextRequest) {
  try {
    const { searchParams } = new URL(request.url);
    const mode = searchParams.get('mode');
    const query = mode ? `?mode=${mode}` : '';
    const res = await fetch(`${BOT_URL}/pnl${query}`, { cache: 'no-store' });
    const data = await res.json();
    return NextResponse.json(data);
  } catch {
    return NextResponse.json({ total_pnl: 0, total_trades: 0, wins: 0, losses: 0, win_rate: 0 }, { status: 503 });
  }
}
