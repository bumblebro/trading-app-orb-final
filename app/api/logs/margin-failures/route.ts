import { NextRequest, NextResponse } from 'next/server';

const BOT_URL = process.env.PYTHON_BOT_URL || 'http://localhost:8000';

export async function GET(request: NextRequest) {
  try {
    const { searchParams } = new URL(request.url);
    const limit = searchParams.get('limit') || '100';

    const res = await fetch(`${BOT_URL}/logs/margin-failures?limit=${limit}`, { cache: 'no-store' });
    const data = await res.json();
    return NextResponse.json(data);
  } catch {
    return NextResponse.json({ logs: [] }, { status: 503 });
  }
}
