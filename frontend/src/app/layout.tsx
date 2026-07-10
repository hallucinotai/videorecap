"use client";

import { useEffect, useState } from "react";
import "./globals.css";
import { AuthContext, useAuthProvider } from "@/lib/auth";
import api from "@/lib/api";
import { AppMetaContext } from "@/lib/app-meta-context";
import { Toaster } from "sonner";
import { GoogleOAuthProvider } from "@react-oauth/google";

declare global {
  interface Window {
    __meta__?: {
      version: string;
      enable_user_api_keys: boolean;
      api_key_restricted_to_emails: boolean;
      enable_api_keys_menu: boolean;
      enable_billing: boolean;
      billing_disabled_message: string | null;
      google_client_id: string | null;
      enable_translation: boolean;
      debug: boolean;
      min_target_duration_seconds?: number;
      max_target_duration_seconds?: number;
    };
  }
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const auth = useAuthProvider();
  const [googleClientId, setGoogleClientId] = useState<string | null>(null);
  const [appMeta, setAppMeta] = useState({ google_client_id: null as string | null });

  useEffect(() => {
    api
      .get("/meta")
      .then((res) => {
        window.__meta__ = res.data;
        const raw = res.data.google_client_id;
        const gid =
          typeof raw === "string" && raw.trim() ? raw.trim() : null;
        setAppMeta({ google_client_id: gid });
        if (gid) {
          setGoogleClientId(gid);
        }
      })
      .catch(() => {});
  }, []);

  const content = (
    <AppMetaContext.Provider value={appMeta}>
      <AuthContext.Provider value={auth}>
        {children}
        <Toaster position="top-right" />
      </AuthContext.Provider>
    </AppMetaContext.Provider>
  );

  return (
    <html lang="en">
      <body className="min-h-screen antialiased">
        {googleClientId ? (
          <GoogleOAuthProvider clientId={googleClientId}>
            {content}
          </GoogleOAuthProvider>
        ) : (
          content
        )}
      </body>
    </html>
  );
}
