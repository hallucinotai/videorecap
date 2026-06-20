"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  Upload,
  ListVideo,
  Key,
  CreditCard,
  Settings,
  Zap,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useAuth } from "@/hooks/useAuth";

const navItems = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/upload", label: "Upload", icon: Upload },
  { href: "/jobs", label: "Jobs", icon: ListVideo },
  { href: "/api-keys", label: "API Keys", icon: Key, metaFlag: "enable_api_keys_menu" as const },
  { href: "/billing", label: "Billing", icon: CreditCard },
  { href: "/settings", label: "Settings", icon: Settings },
  { href: "/feature-flags", label: "Feature Flags", icon: Zap, adminOnly: true },
];

export function Sidebar() {
  const pathname = usePathname();
  const { user } = useAuth();
  const [version, setVersion] = useState<string>("");
  const [meta, setMeta] = useState<typeof window.__meta__>(undefined);

  useEffect(() => {
    const check = () => {
      setVersion(window.__meta__?.version || "");
      setMeta(window.__meta__);
    };
    check();
    const t = setTimeout(check, 2000);
    return () => clearTimeout(t);
  }, []);

  return (
    <nav className="flex w-56 flex-col border-r bg-secondary/30 p-4">
      <ul className="flex-1 space-y-1">
        {navItems
          .filter((item) => {
            if (item.adminOnly) return user?.is_admin ?? false;
            if (!item.metaFlag) return true;
            return meta?.[item.metaFlag] !== false;
          })
          .map((item) => (
            <li key={item.href}>
              <Link
                href={item.href}
                className={cn(
                  "flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors",
                  pathname === item.href
                    ? "bg-primary text-primary-foreground"
                    : "text-muted-foreground hover:bg-secondary hover:text-foreground"
                )}
              >
                <item.icon className="h-4 w-4" />
                {item.label}
              </Link>
            </li>
          ))}
      </ul>
      {version && (
        <p className="px-3 text-xs text-muted-foreground/60">{version}</p>
      )}
    </nav>
  );
}
