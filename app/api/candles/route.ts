import { NextResponse } from 'next/server';

const BOT_URL = process.env.PYTHON_BOT_URL || 'http://localhost:8000';

export async function GET() {
  try {
    const res = await fetch(`${BOT_URL}/candles`, { cache: 'no-store' });
    const data = await res.json();
    return NextResponse.json(data);
  } catch {
    return NextResponse.json({ 
      candles: [], 
      orb_high: [], 
      orb_low: [], 
      fibonacci: {}, 
      fibonacci_direction: null,
      entry_zone_high: null,
      entry_zone_low: null,
      stop_loss_level: null,
      macd_histogram: [],
      macd_current: {}
    }, { status: 503 });
  }
}
