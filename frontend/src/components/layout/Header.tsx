"use client";

import { useRouter } from "next/navigation";
import { useAuth } from "@/hooks/useAuth";
import { LogOut, User, Shield } from "lucide-react";

export function Header() {
  const { user, logout } = useAuth();
  const router = useRouter();

  const handleLogout = () => {
    logout();
    router.push("/login");
  };

  return (
    <header className="flex h-14 items-center justify-between border-b px-6">
      <h1 className="text-lg font-semibold">Video Recap Agent</h1>
      <div className="flex items-center gap-4">
        <span className="flex items-center gap-2 text-sm text-muted-foreground">
          <User className="h-4 w-4" />
          {user?.full_name}
        </span>
        <div className="flex items-center gap-2">
          {user?.is_admin && (
            <span className="flex items-center gap-1 rounded-full bg-amber-100 text-amber-900 px-2 py-0.5 text-xs uppercase font-semibold">
              <Shield className="h-3 w-3" />
              Admin
            </span>
          )}
          <span className="rounded-full bg-secondary px-2 py-0.5 text-xs uppercase">
            {user?.tier}
          </span>
        </div>
        <button
          onClick={handleLogout}
          className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
        >
          <LogOut className="h-4 w-4" />
          Logout
        </button>
      </div>
    </header>
  );
}
