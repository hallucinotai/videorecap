"use client";

import { useEffect, useState } from "react";
import { Globe } from "lucide-react";
import type { JobConfig } from "@/lib/types";

interface UploadFormProps {
  onSubmit: (config: JobConfig) => void;
  disabled?: boolean;
}

const DEFAULT_MIN_DURATION = 10;
const DEFAULT_MAX_DURATION = 300;

export function UploadForm({ onSubmit, disabled }: UploadFormProps) {
  const [minDuration, setMinDuration] = useState(DEFAULT_MIN_DURATION);
  const [maxDuration, setMaxDuration] = useState(DEFAULT_MAX_DURATION);
  const [targetDuration, setTargetDuration] = useState(30);
  const [voice, setVoice] = useState("nova");
  const [language, setLanguage] = useState("");
  const [translateTo, setTranslateTo] = useState("");
  const [includeEmotions, setIncludeEmotions] = useState(false);

  useEffect(() => {
    const applyMeta = () => {
      const meta = window.__meta__;
      if (!meta) return;
      const min =
        typeof meta.min_target_duration_seconds === "number"
          ? meta.min_target_duration_seconds
          : DEFAULT_MIN_DURATION;
      const max =
        typeof meta.max_target_duration_seconds === "number"
          ? meta.max_target_duration_seconds
          : DEFAULT_MAX_DURATION;
      setMinDuration(min);
      setMaxDuration(max);
      setTargetDuration((prev) => Math.min(max, Math.max(min, prev)));
    };
    applyMeta();
    const id = window.setInterval(applyMeta, 500);
    const stop = window.setTimeout(() => window.clearInterval(id), 5000);
    return () => {
      window.clearInterval(id);
      window.clearTimeout(stop);
    };
  }, []);

  const translationEnabled = typeof window !== "undefined" && window.__meta__?.enable_translation === true;

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onSubmit({
      target_duration: targetDuration,
      whisper_model: "small",
      tts_voice: voice,
      tts_model: "tts-1",
      language: translationEnabled ? language || undefined : "en",
      translate_to: translationEnabled ? translateTo || undefined : undefined,
      pad_with_black: false,
      include_emotions: includeEmotions,
    });
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4 rounded-lg border p-6">
      <h3 className="text-lg font-semibold">Recap Settings</h3>
      <div>
        <label className="mb-1 block text-sm font-medium">
          Target Duration (seconds)
        </label>
        <input
          type="number"
          min={minDuration}
          max={maxDuration}
          value={targetDuration}
          onChange={(e) => setTargetDuration(Number(e.target.value))}
          className="w-full rounded-md border px-3 py-2 text-sm"
        />
        <p className="mt-1 text-xs text-muted-foreground">
          Allowed range: {minDuration}–{maxDuration}s
        </p>
      </div>
      <div>
        <label className="mb-1 block text-sm font-medium">
          Narration Voice
        </label>
        <select
          value={voice}
          onChange={(e) => setVoice(e.target.value)}
          className="w-full rounded-md border px-3 py-2 text-sm"
        >
          <option value="alloy">Alloy</option>
          <option value="echo">Echo</option>
          <option value="fable">Fable</option>
          <option value="onyx">Onyx</option>
          <option value="nova">Nova</option>
          <option value="shimmer">Shimmer</option>
        </select>
      </div>
      <div className="rounded-md border border-blue-200 bg-blue-50 p-4">
        <label className="flex items-center gap-3">
          <input
            type="checkbox"
            checked={includeEmotions}
            onChange={(e) => setIncludeEmotions(e.target.checked)}
            className="h-4 w-4 rounded border-gray-300"
          />
          <div className="flex-1">
            <div className="font-medium text-sm text-blue-900">
              ✨ Include Emotion Analysis (Premium)
            </div>
            <div className="text-xs text-blue-700 mt-1">
              Analyzes speaker emotions to improve clip selection and narration tone. Adds ~5-8 seconds processing time.
            </div>
          </div>
        </label>
      </div>
      {translationEnabled ? (
        <>
          <div>
            <label className="mb-1 block text-sm font-medium">
              Source Language (optional)
            </label>
            <input
              type="text"
              value={language}
              onChange={(e) => setLanguage(e.target.value)}
              placeholder="Auto-detect"
              className="w-full rounded-md border px-3 py-2 text-sm"
            />
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium">
              Translate to (optional)
            </label>
            <input
              type="text"
              value={translateTo}
              onChange={(e) => setTranslateTo(e.target.value)}
              placeholder="e.g. Tamil"
              className="w-full rounded-md border px-3 py-2 text-sm"
            />
          </div>
        </>
      ) : (
        <div className="rounded-md border border-dashed border-muted-foreground/30 bg-muted/40 px-4 py-3">
          <div className="flex items-center gap-2 text-sm font-medium text-muted-foreground">
            <Globe className="h-4 w-4" />
            Language Support
          </div>
          <p className="mt-1 text-xs text-muted-foreground">
            Currently supports <span className="font-medium text-foreground">English</span> videos with English narration.
          </p>
          <p className="mt-0.5 text-xs text-muted-foreground/70">
            Multi-language support &amp; translation coming soon.
          </p>
        </div>
      )}
      <button
        type="submit"
        disabled={disabled}
        className="w-full rounded-md bg-primary py-2 text-sm text-primary-foreground hover:opacity-90 disabled:opacity-50"
      >
        Start Processing
      </button>
    </form>
  );
}
