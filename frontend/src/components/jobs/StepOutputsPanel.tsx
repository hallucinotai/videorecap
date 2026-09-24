"use client";

import { useState } from "react";
import { Download, FileJson, Sparkles, Layers } from "lucide-react";
import { toast } from "sonner";
import type { EnrichmentLayerFile, Job, IntermediateFile } from "@/lib/types";

type IntermediateKey = "emotions" | "scene_understanding";

interface StepOutput {
  key: IntermediateKey;
  label: string;
  description: string;
  defaultFilename: string;
  icon: typeof FileJson;
  iconWrapClass: string;
}

/** Step-1-only extras (enrichment layers are listed separately). */
const STEP_OUTPUTS: StepOutput[] = [
  {
    key: "emotions",
    label: "Audio emotions",
    description: "Per-segment emotion analysis (JSON, PREMIUM)",
    defaultFilename: "emotions.json",
    icon: Sparkles,
    iconWrapClass:
      "bg-purple-100 text-purple-700 dark:bg-purple-950/60 dark:text-purple-300",
  },
  {
    key: "scene_understanding",
    label: "Scene understanding",
    description: "Visual scene describe (injected into L4)",
    defaultFilename: "scene_understanding.json",
    icon: FileJson,
    iconWrapClass:
      "bg-amber-100 text-amber-700 dark:bg-amber-950/60 dark:text-amber-300",
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
  className,
}: {
  icon: typeof FileJson;
  iconWrapClass: string;
  label: string;
  description: string;
  sizeMb: number | null | undefined;
  available: boolean;
  busy: boolean;
  onDownload: () => void;
  className?: string;
}) {
  const Icon = icon;
  return (
    <div className={`flex items-center gap-3 px-3 py-2.5 sm:px-4 ${className ?? ""}`}>
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
    </div>
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
  const hasExtrasSection = STEP_OUTPUTS.some((output) => {
    const file = intermediates[output.key];
    return !!file?.download_url;
  });

  if (!hasEnrichmentSection && !hasExtrasSection) {
    return null;
  }

  return (
    <div className="rounded-lg border p-4 sm:p-6">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold">Step 1 outputs</h3>
          <p className="mt-0.5 text-xs text-muted-foreground">
            Enrichment layers and scene understanding artifacts.
          </p>
        </div>
        <span className="rounded-full border border-amber-300 bg-amber-50 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-amber-800 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-300">
          Debug
        </span>
      </div>

      {hasEnrichmentSection && (
        <div className={hasExtrasSection ? "mb-4" : undefined}>
          <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Enrichment layers
          </h4>
          <ul className="divide-y rounded-md border">
            {enrichmentLayers.map((layer) => (
              <li
                key={layer.layer_id}
                className={layer.is_sublayer ? "pl-4 sm:pl-6" : undefined}
              >
                <OutputRow
                  className={layer.is_sublayer ? "border-l-2 border-teal-200/80 dark:border-teal-900" : undefined}
                  icon={layer.layer_id === "L0" ? FileJson : Layers}
                  iconWrapClass={
                    layer.is_sublayer
                      ? "bg-teal-50 text-teal-600 dark:bg-teal-950/40 dark:text-teal-400"
                      : layer.layer_id === "L0"
                        ? "bg-sky-100 text-sky-700 dark:bg-sky-950/60 dark:text-sky-300"
                        : "bg-teal-100 text-teal-700 dark:bg-teal-950/60 dark:text-teal-300"
                  }
                  label={layer.is_sublayer ? layer.label : `${layer.layer_id}: ${layer.label}`}
                  description={layer.description}
                  sizeMb={layer.size_mb}
                  available={layer.available}
                  busy={busyKey === layer.layer_id}
                  onDownload={() => handleLayerDownload(layer)}
                />
              </li>
            ))}
          </ul>
        </div>
      )}

      {hasExtrasSection && (
        <div>
          {hasEnrichmentSection && (
            <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Step 1 extras
            </h4>
          )}
          <ul className="divide-y rounded-md border">
            {STEP_OUTPUTS.map((output) => {
              const file = intermediates[output.key] as IntermediateFile | undefined;
              const available = !!file && !!file.download_url;
              const busy = busyKey === output.key;

              return (
                <li key={output.key}>
                  <OutputRow
                    icon={output.icon}
                    iconWrapClass={output.iconWrapClass}
                    label={output.label}
                    description={output.description}
                    sizeMb={file?.size_mb}
                    available={available}
                    busy={busy}
                    onDownload={() => file && handleStepDownload(output, file)}
                  />
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </div>
  );
}
