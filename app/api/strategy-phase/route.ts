import { NextResponse } from 'next/server';

const BOT_URL = process.env.PYTHON_BOT_URL || 'http://localhost:8000';

export async function GET() {
  try {
    const res = await fetch(`${BOT_URL}/strategy-phase`, { cache: 'no-store' });
    const data = await res.json();
    return NextResponse.json(data);
  } catch {
    return NextResponse.json({ phase: 'DISCONNECTED', phase_description: 'Bot server disconnected', breakout_direction: null, breakout_price: null, breakout_time: null, pullback_timer_remaining: null, pullback_reached: false, fibonacci_levels: null }, { status: 503 });
  }
}
