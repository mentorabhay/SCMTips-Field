"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import React from "react";

const TABS = [
  { href: "/warehouse/board", label: "Board" },
  { href: "/warehouse/receiving", label: "Receiving" },
  { href: "/warehouse/inventory", label: "Counts" },
  { href: "/warehouse/discrepancies", label: "Discrepancies" },
  { href: "/warehouse/accuracy", label: "Accuracy" },
  { href: "/warehouse/queues", label: "Posting queues" },
] as const;

export function WarehouseTabs() {
  const path = usePathname();
  return (
    <nav aria-label="Warehouse" className="mb-3">
      <ul className="m-0 flex list-none flex-wrap gap-1.5 p-0">
        {TABS.map((t) => {
          const on = path === t.href;
          return (
            <li key={t.href}>
              <Link
                href={t.href}
                aria-current={on ? "page" : undefined}
                className={`inline-flex min-h-[40px] items-center rounded-md px-3 font-bold no-underline ${
                  on ? "bg-primary text-white hover:text-white" : "bg-card text-ink hover:text-ink"
                }`}
              >
                {t.label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
