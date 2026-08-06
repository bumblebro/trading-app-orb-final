'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';

const links = [
  { href: '/', label: 'Dashboard', short: 'Home' },
  { href: '/trades', label: 'Trades', short: 'Trades' },
  { href: '/settings', label: 'Settings', short: 'Settings' },
];

export default function Navbar() {
  const pathname = usePathname();

  return (
    <header className="sticky top-0 z-50 border-b border-[var(--border)] bg-[var(--bg)]/85 backdrop-blur">
      <div className="mx-auto flex h-12 max-w-[1400px] items-center gap-3 px-4 sm:h-14 sm:gap-6 sm:px-5">
        <Link href="/" className="flex shrink-0 items-baseline gap-2 no-underline">
          <span className="text-[0.95rem] font-bold tracking-tight text-[var(--text)]">ORB</span>
          <span className="label hidden sm:inline">Nifty 50</span>
        </Link>

        <nav className="flex min-w-0 flex-1 items-center gap-0.5 overflow-x-auto sm:gap-1">
          {links.map((link) => {
            const active = pathname === link.href;
            return (
              <Link
                key={link.href}
                href={link.href}
                className={`shrink-0 rounded-lg px-2.5 py-1.5 text-[0.78rem] font-medium no-underline transition-colors sm:px-3 sm:text-[0.82rem] ${
                  active
                    ? 'bg-[var(--surface-2)] text-[var(--text)]'
                    : 'text-[var(--muted)] hover:text-[var(--text)]'
                }`}
              >
                <span className="sm:hidden">{link.short}</span>
                <span className="hidden sm:inline">{link.label}</span>
              </Link>
            );
          })}
        </nav>
      </div>
    </header>
  );
}
