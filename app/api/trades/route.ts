import { NextRequest, NextResponse } from 'next/server';

const BOT_URL = process.env.PYTHON_BOT_URL || 'http://localhost:8000';

export async function GET(request: NextRequest) {
  try {
    const { searchParams } = new URL(request.url);
    const params = new URLSearchParams();
    if (searchParams.get('mode')) params.set('mode', searchParams.get('mode')!);
    if (searchParams.get('date_from')) params.set('date_from', searchParams.get('date_from')!);
    if (searchParams.get('date_to')) params.set('date_to', searchParams.get('date_to')!);
    const query = params.toString();

    const res = await fetch(`${BOT_URL}/trades${query ? `?${query}` : ''}`, { cache: 'no-store' });
    const data = await res.json();
    return NextResponse.json(data);
  } catch {
    return NextResponse.json({ trades: [] }, { status: 503 });
  }
}
