import { NextRequest, NextResponse } from 'next/server';

const BOT_URL = process.env.PYTHON_BOT_URL || 'http://localhost:8000';

export async function GET(request: NextRequest) {
  try {
    const { searchParams } = new URL(request.url);
    const params = new URLSearchParams();
    if (searchParams.get('limit')) params.set('limit', searchParams.get('limit')!);
    if (searchParams.get('category')) params.set('category', searchParams.get('category')!);
    const query = params.toString();

    const res = await fetch(`${BOT_URL}/logs${query ? `?${query}` : ''}`, { cache: 'no-store' });
    const data = await res.json();
    return NextResponse.json(data);
  } catch {
    return NextResponse.json({ logs: [] }, { status: 503 });
  }
}
