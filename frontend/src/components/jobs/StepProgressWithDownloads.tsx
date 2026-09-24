"use client";

import { Download } from "lucide-react";
import { toast } from "sonner";
import type { Job, IntermediateFile } from "@/lib/types";

const STEP_NAMES = [
  "",
  "Transcribe & enrich",
];

interface StepProgressWithDownloadsProps {
  activeStep: number;
  job: Job;
  isDebug: boolean;
  onDownload: (endpoint: string, filename: string) => Promise<void>;
}

export function StepProgressWithDownloads({
  activeStep,
  job,
  isDebug,
  onDownload,
}: StepProgressWithDownloadsProps) {
  const baseName = job.original_filename.replace(/\.[^.]+$/, "") || "recap";

  const handleDownloadStep = async () => {
    const intermediate = job.intermediate_keys_detailed?.["transcription"];

    if (!intermediate || !intermediate.download_url) {
      toast.error("Download not available for this step");
      return;
    }

    await onDownload(intermediate.download_url, `${baseName}_transcription`);
  };

  const getStepIntermediate = (): IntermediateFile | null => {
    if (!isDebug) return null;
    return job.intermediate_keys_detailed?.["transcription"] || null;
  };

  const step = 1;
  const isCompleted = step <= activeStep || job.status === "completed";
  const isActive = step === activeStep && job.status !== "completed";
  const canDownload = isCompleted && isDebug && getStepIntermediate();

  return (
    <div className="space-y-2">
      <div className="mt-4 grid grid-cols-1 gap-2">
        <div className="flex flex-col items-center gap-1">
          <div className="relative">
            <div
              className={`mx-auto h-2 w-2 rounded-full transition-all ${
                isCompleted
                  ? "bg-green-500"
                  : isActive
                    ? "bg-blue-500"
                    : "bg-gray-200"
              }`}
            />
            {canDownload && (
              <button
                type="button"
                onClick={handleDownloadStep}
                className="absolute -right-3 -top-1 rounded-full bg-green-100 p-1 text-green-700 transition-colors hover:bg-green-200"
                title={`Download ${STEP_NAMES[step]}`}
                aria-label={`Download ${STEP_NAMES[step]}`}
              >
                <Download className="h-3 w-3" />
              </button>
            )}
          </div>

          <p className="text-[10px] text-muted-foreground">{STEP_NAMES[step]}</p>
        </div>
      </div>
    </div>
  );
}
