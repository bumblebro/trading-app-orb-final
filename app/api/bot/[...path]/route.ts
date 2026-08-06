import { NextRequest, NextResponse } from 'next/server';

/**
 * Single proxy between the browser and the Python bot.
 *
 * The API token lives only in the server environment, so the browser never
 * holds a credential that could start or stop live trading.
 */

const BOT_URL = process.env.PYTHON_BOT_URL || 'http://localhost:8000';
const BOT_TOKEN = process.env.BOT_API_TOKEN || '';
const TIMEOUT_MS = 8000;

function botHeaders(): HeadersInit {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (BOT_TOKEN) headers.Authorization = `Bearer ${BOT_TOKEN}`;
  return headers;
}

async function forward(request: NextRequest, path: string[], body?: string) {
  const target = `${BOT_URL}/${path.join('/')}${request.nextUrl.search}`;
  try {
    const res = await fetch(target, {
      method: body === undefined ? 'GET' : 'POST',
      headers: botHeaders(),
      body,
      cache: 'no-store',
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });

    const text = await res.text();
    const payload = text ? JSON.parse(text) : {};
    return NextResponse.json(payload, { status: res.status });
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Unknown error';
    return NextResponse.json(
      { error: `Bot server unreachable: ${message}`, offline: true },
      { status: 503 },
    );
  }
}

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
) {
  const { path } = await params;
  return forward(request, path);
}

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
) {
  const { path } = await params;
  const body = await request.text();
  return forward(request, path, body || '{}');
}
