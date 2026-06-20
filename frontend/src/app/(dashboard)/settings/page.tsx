"use client";

import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { useAuth } from "@/hooks/useAuth";
import api from "@/lib/api";
import type { FeatureFlags } from "@/lib/types";
import { formatDate } from "@/lib/utils";

function APIKeySection({
  title,
  description,
  hasKey,
  endpoint,
  placeholder,
  successMessage,
  helpLink,
  helpText,
}: {
  title: string;
  description: string;
  hasKey: boolean;
  endpoint: string;
  placeholder: string;
  successMessage: string;
  helpLink?: string;
  helpText?: string;
}) {
  const [key, setKey] = useState("");
  const [saving, setSaving] = useState(false);
  const [removing, setRemoving] = useState(false);
  const [saved, setSaved] = useState(hasKey);

  const handleSave = async () => {
    if (!key.trim()) {
      toast.error("API key cannot be empty");
      return;
    }
    setSaving(true);
    try {
      const bodyKey = endpoint.includes("openai") ? "openai_api_key" : "assemblyai_api_key";
      await api.put(endpoint, { [bodyKey]: key.trim() });
      toast.success(successMessage);
      setSaved(true);
      setKey("");
    } catch {
      toast.error(`Failed to save API key`);
    } finally {
      setSaving(false);
    }
  };

  const handleRemove = async () => {
    setRemoving(true);
    try {
      await api.delete(endpoint);
      toast.success("API key removed");
      setSaved(false);
    } catch {
      toast.error("Failed to remove API key");
    } finally {
      setRemoving(false);
    }
  };

  return (
    <div className="rounded-lg border p-6">
      <h3 className="mb-1 font-semibold">{title}</h3>
      <p className="mb-4 text-sm text-muted-foreground">{description}</p>

      {helpLink && helpText && (
        <p className="mb-4 text-sm">
          <a
            href={helpLink}
            target="_blank"
            rel="noopener noreferrer"
            className="text-blue-600 hover:underline"
          >
            {helpText} ↗
          </a>
        </p>
      )}

      <div className="mb-3 flex items-center gap-2 text-sm">
        <span
          className={`inline-block h-2 w-2 rounded-full ${saved ? "bg-green-500" : "bg-red-500"}`}
        />
        <span className={saved ? "text-green-700" : "text-red-700"}>
          {saved ? "Key saved" : "Key required"}
        </span>
      </div>

      <div className="flex gap-2">
        <input
          type="password"
          value={key}
          onChange={(e) => setKey(e.target.value)}
          placeholder={saved ? "Enter new key to replace" : placeholder}
          className="flex-1 rounded-md border px-3 py-2 text-sm"
        />
        <button
          onClick={handleSave}
          disabled={saving || !key.trim()}
          className="rounded-md bg-primary px-4 py-2 text-sm text-primary-foreground hover:opacity-90 disabled:opacity-50"
        >
          {saving ? "Saving..." : saved ? "Update" : "Save"}
        </button>
      </div>

      {saved && (
        <button
          onClick={handleRemove}
          disabled={removing}
          className="mt-3 text-sm text-red-600 hover:underline disabled:opacity-50"
        >
          {removing ? "Removing..." : "Remove saved key"}
        </button>
      )}
    </div>
  );
}

export default function SettingsPage() {
  const { user } = useAuth();
  const [flags, setFlags] = useState<FeatureFlags | null>(null);

  useEffect(() => {
    api
      .get<FeatureFlags>("/auth/feature-flags")
      .then((res) => setFlags(res.data))
      .catch(() => setFlags({ requires_openai_api_key: false, requires_assemblyai_key: true }));
  }, []);

  if (!user) return null;

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <h2 className="text-2xl font-bold">Settings</h2>

      <div className="rounded-lg border p-6">
        <h3 className="mb-4 font-semibold">Profile</h3>
        <dl className="space-y-4 text-sm">
          <div>
            <dt className="text-muted-foreground">Name</dt>
            <dd className="font-medium">{user.full_name}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">Email</dt>
            <dd className="font-medium">{user.email}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">Auth Provider</dt>
            <dd className="font-medium capitalize">{user.auth_provider}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">Plan</dt>
            <dd className="font-medium capitalize">{user.tier}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">Member Since</dt>
            <dd className="font-medium">{formatDate(user.created_at)}</dd>
          </div>
        </dl>
      </div>

      {flags?.requires_openai_api_key && (
        <APIKeySection
          title="OpenAI API Key"
          description="Your key is encrypted at rest and used for transcription, recap generation, and narration."
          hasKey={user.has_openai_key}
          endpoint="/auth/me/openai-key"
          placeholder="sk-..."
          successMessage="OpenAI API key saved"
        />
      )}

      {flags?.requires_assemblyai_key && (
        <APIKeySection
          title="AssemblyAI API Key"
          description="Used for advanced speaker diarization in video transcription. Get free credits with a new account."
          hasKey={user.has_assemblyai_key}
          endpoint="/auth/me/assemblyai-key"
          placeholder="aai_..."
          successMessage="AssemblyAI API key saved"
          helpLink="https://www.assemblyai.com/dashboard/activation"
          helpText="Get free API key with credits"
        />
      )}

      <div className="rounded-lg border p-6">
        <h3 className="mb-1 font-semibold">Transcription cache (Whisper)</h3>
        <p className="mb-4 text-sm text-muted-foreground">
          The service keeps the AI transcription model loaded in memory so repeat jobs start
          faster. If you see strange failures on back‑to‑back runs, clear this cache so the next
          job loads a fresh model (slightly slower once).
        </p>
        <ClearWhisperCacheButton />
      </div>
    </div>
  );
}

function ClearWhisperCacheButton() {
  const [loading, setLoading] = useState(false);

  const handleClear = async () => {
    setLoading(true);
    try {
      await api.post("/processing/clear-whisper-cache");
      toast.success(
        "Cache clear scheduled. Start your next job — Whisper will reload on the server workers.",
      );
    } catch {
      toast.error("Could not clear cache. Try again or contact support.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <button
      type="button"
      onClick={handleClear}
      disabled={loading}
      className="rounded-md border border-amber-600/50 bg-amber-50 px-4 py-2 text-sm font-medium text-amber-950 hover:bg-amber-100 disabled:opacity-50 dark:bg-amber-950/30 dark:text-amber-50 dark:hover:bg-amber-900/40"
    >
      {loading ? "Clearing…" : "Clear Whisper model cache"}
    </button>
  );
}
