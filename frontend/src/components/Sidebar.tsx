"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import clsx from "clsx";

const NAV = [
  { href: "/", label: "Dashboard", icon: "~" },
  { href: "/events", label: "Live Events", icon: ">" },
  { href: "/news", label: "News Monitor", icon: "#" },
  { href: "/candidates", label: "Candidate Funnel", icon: "^" },
  { href: "/options", label: "Options Decision", icon: "$" },
  { href: "/trades", label: "Trades", icon: "%" },
  { href: "/ticker", label: "Ticker View", icon: "@" },
  { href: "/health", label: "System Health", icon: "*" },
];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="fixed left-0 top-0 h-full w-56 bg-slate-900 border-r border-slate-700 flex flex-col z-50">
      <div className="p-4 border-b border-slate-700">
        <h1 className="text-lg font-bold text-blue-400">Sentiment</h1>
        <p className="text-xs text-slate-400">Options Lab</p>
      </div>
      <nav className="flex-1 py-2">
        {NAV.map((item) => (
          <Link
            key={item.href}
            href={item.href}
            className={clsx(
              "flex items-center px-4 py-2.5 text-sm transition-colors",
              pathname === item.href
                ? "bg-slate-800 text-blue-400 border-r-2 border-blue-400"
                : "text-slate-400 hover:text-slate-200 hover:bg-slate-800/50"
            )}
          >
            <span className="w-6 text-center font-mono mr-2">{item.icon}</span>
            {item.label}
          </Link>
        ))}
      </nav>
      <div className="p-3 border-t border-slate-700 text-xs text-slate-500">
        Paper Trading - SIM
      </div>
    </aside>
  );
}
