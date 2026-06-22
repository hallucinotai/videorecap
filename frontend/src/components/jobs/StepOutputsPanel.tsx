"use client";

import { useState } from "react";
import { Download, FileJson, FileAudio, FileVideo, Sparkles, Layers } from "lucide-react";
import { toast } from "sonner";
import type { EnrichmentLayerFile, Job, IntermediateFile } from "@/lib/types";

type IntermediateKey =
  | "translation"
  | "recap_data"
  | "tts_audio"
  | "recap_video"
  | "emotions";

interface StepOutput {
  key: IntermediateKey;
  step: number | null;
  label: string;
  description: string;
  defaultFilename: string;
  icon: typeof FileJson;
  iconWrapClass: string;
}

const STEP_OUTPUTS: StepOutput[] = [
  {
    key: "emotions",
    step: null,
    label: "Audio emotions",
    description: "Per-segment emotion analysis (JSON, PREMIUM)",
    defaultFilename: "emotions.json",
    icon: Sparkles,
    iconWrapClass:
      "bg-purple-100 text-purple-700 dark:bg-purple-950/60 dark:text-purple-300",
  },
  {
    key: "translation",
    step: 2,
    label: "Translation",
    description: "Translated transcript (JSON)",
    defaultFilename: "translated.json",
    icon: FileJson,
    iconWrapClass:
      "bg-indigo-100 text-indigo-700 dark:bg-indigo-950/60 dark:text-indigo-300",
  },
  {
    key: "recap_data",
    step: 3,
    label: "Recap plan",
    description: "Selected clips + narration text (JSON)",
    defaultFilename: "recap_data.json",
    icon: FileJson,
    iconWrapClass:
      "bg-amber-100 text-amber-700 dark:bg-amber-950/60 dark:text-amber-300",
  },
  {
    key: "tts_audio",
    step: 4,
    label: "Narration audio",
    description: "TTS-generated voiceover (MP3)",
    defaultFilename: "recap_narration.mp3",
    icon: FileAudio,
    iconWrapClass:
      "bg-rose-100 text-rose-700 dark:bg-rose-950/60 dark:text-rose-300",
  },
  {
    key: "recap_video",
    step: 5,
    label: "Clipped video",
    description: "Concatenated clips, no narration (MP4)",
    defaultFilename: "recap_video.mp4",
    icon: FileVideo,
    iconWrapClass:
      "bg-emerald-100 text-emerald-700 dark:bg-emerald-950/60 dark:text-emerald-300",
  },
];

interface StepOutputsPanelProps {
  job: Job;
  onDownload: (endpoint: string, filename: string) => Promise<void>;
}

function OutputRow({
  icon,
  iconWrapClass,
  label,
  description,
  sizeMb,
  available,
  busy,
  onDownload,
}: {
  icon: typeof FileJson;
  iconWrapClass: string;
  label: string;
  description: string;
  sizeMb: number | null | undefined;
  available: boolean;
  busy: boolean;
  onDownload: () => void;
}) {
  const Icon = icon;
  return (
    <li className="flex items-center gap-3 px-3 py-2.5 sm:px-4">
      <div
        className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-md ${iconWrapClass}`}
      >
        <Icon className="h-4 w-4" />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline gap-x-2">
          <span className="text-sm font-medium">{label}</span>
          {available && sizeMb != null && (
            <span className="text-xs text-muted-foreground">{sizeMb} MB</span>
          )}
        </div>
        <p className="truncate text-xs text-muted-foreground">{description}</p>
      </div>
      <button
        type="button"
        disabled={!available || busy}
        onClick={onDownload}
        className="flex shrink-0 items-center gap-1.5 rounded-md border border-primary/30 px-2.5 py-1.5 text-xs font-medium text-primary transition-colors hover:bg-primary/10 disabled:cursor-not-allowed disabled:border-muted disabled:text-muted-foreground disabled:hover:bg-transparent"
        title={available ? `Download ${label}` : "Not generated for this job"}
      >
        <Download className={`h-3.5 w-3.5 ${busy ? "animate-pulse" : ""}`} />
        {busy ? "..." : available ? "Download" : "N/A"}
      </button>
    </li>
  );
}

export function StepOutputsPanel({ job, onDownload }: StepOutputsPanelProps) {
  const intermediates = job.intermediate_keys_detailed || {};
  const enrichmentLayers = job.enrichment_layers || [];
  const baseName = job.original_filename.replace(/\.[^.]+$/, "") || "recap";
  const [busyKey, setBusyKey] = useState<string | null>(null);

  const handleStepDownload = async (output: StepOutput, file: IntermediateFile) => {
    if (!file.download_url) {
      toast.error("Download URL is not available for this step");
      return;
    }
    setBusyKey(output.key);
    try {
      await onDownload(file.download_url, `${baseName}_${output.defaultFilename}`);
    } finally {
      setBusyKey(null);
    }
  };

  const handleLayerDownload = async (layer: EnrichmentLayerFile) => {
    if (!layer.download_url) {
      toast.error("Download URL is not available for this layer");
      return;
    }
    setBusyKey(layer.layer_id);
    try {
      await onDownload(layer.download_url, `${baseName}_${layer.filename}`);
    } finally {
      setBusyKey(null);
    }
  };

  const hasEnrichmentSection = enrichmentLayers.length > 0;
  const hasPipelineSection = STEP_OUTPUTS.some((output) => {
    const file = intermediates[output.key];
    return !!file?.download_url;
  });

  return (
    <div className="rounded-lg border p-4 sm:p-6">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold">Step outputs</h3>
          <p className="mt-0.5 text-xs text-muted-foreground">
            Download intermediate files and enrichment layer artifacts.
          </p>
        </div>
        <span className="rounded-full border border-amber-300 bg-amber-50 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-amber-800 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-300">
          Debug
        </span>
      </div>

      {hasEnrichmentSection && (
        <div className="mb-4">
          <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Enrichment layers
          </h4>
          <ul className="divide-y rounded-md border">
            {enrichmentLayers.map((layer) => (
              <OutputRow
                key={layer.layer_id}
                icon={layer.layer_id === "L0" ? FileJson : Layers}
                iconWrapClass={
                  layer.layer_id === "L0"
                    ? "bg-sky-100 text-sky-700 dark:bg-sky-950/60 dark:text-sky-300"
                    : "bg-teal-100 text-teal-700 dark:bg-teal-950/60 dark:text-teal-300"
                }
                label={`${layer.layer_id}: ${layer.label}`}
                description={layer.description}
                sizeMb={layer.size_mb}
                available={layer.available}
                busy={busyKey === layer.layer_id}
                onDownload={() => handleLayerDownload(layer)}
              />
            ))}
          </ul>
        </div>
      )}

      {hasPipelineSection && (
        <div>
          {hasEnrichmentSection && (
            <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Pipeline outputs
            </h4>
          )}
          <ul className="divide-y rounded-md border">
            {STEP_OUTPUTS.map((output) => {
              const file = intermediates[output.key] as IntermediateFile | undefined;
              const available = !!file && !!file.download_url;
              const busy = busyKey === output.key;

              return (
                <OutputRow
                  key={output.key}
                  icon={output.icon}
                  iconWrapClass={output.iconWrapClass}
                  label={
                    output.step !== null
                      ? `Step ${output.step}: ${output.label}`
                      : output.label
                  }
                  description={output.description}
                  sizeMb={file?.size_mb}
                  available={available}
                  busy={busy}
                  onDownload={() => file && handleStepDownload(output, file)}
                />
              );
            })}
          </ul>
        </div>
      )}
    </div>
  );
}
