"use client";

import { useState } from "react";
import { Download, ChevronDown } from "lucide-react";
import { toast } from "sonner";
import type { Job, IntermediateFile } from "@/lib/types";

const STEP_NAMES = [
  "",
  "Transcribing video",
  "Translating transcription",
  "Generating recap",
  "Generating narration",
  "Extracting clips",
  "Removing audio",
  "Merging final video",
];

interface StepProgressWithDownloadsProps {
  activeStep: number;
  job: Job;
  isDebug: boolean;
  onDownload: (endpoint: string, filename: string) => Promise<void>;
}

const intermediateMap: Record<number, string> = {
  1: "transcription",
  2: "translation",
  3: "recap_data",
  4: "tts_audio",
  5: "recap_video",
};

export function StepProgressWithDownloads({
  activeStep,
  job,
  isDebug,
  onDownload,
}: StepProgressWithDownloadsProps) {
  const [expandedStep, setExpandedStep] = useState<number | null>(null);

  const handleDownloadStep = async (step: number) => {
    const intermediateKey = intermediateMap[step as keyof typeof intermediateMap];
    const intermediate = job.intermediate_keys_detailed?.[intermediateKey];

    if (!intermediate || !intermediate.download_url) {
      toast.error("Download not available for this step");
      return;
    }

    try {
      await onDownload(intermediate.download_url, `${job.id}_${intermediateKey}`);
      // Success toast is handled by JobDetailContent handleFileDownload
    } catch (error) {
      // Error toast is handled by JobDetailContent handleFileDownload
      throw error;
    }
  };

  const getStepIntermediate = (step: number): IntermediateFile | null => {
    if (!isDebug) return null;
    const key = intermediateMap[step as keyof typeof intermediateMap];
    return (key && job.intermediate_keys_detailed?.[key]) || null;
  };

  const hasTranslation = job.config.translate_to !== null && job.config.translate_to !== undefined;

  return (
    <div className="space-y-2">
      <div className="mt-4 grid grid-cols-7 gap-2">
        {[1, 2, 3, 4, 5, 6, 7].map((step) => {
          const isCompleted = step < activeStep;
          const isActive = step === activeStep;
          const canDownload = isCompleted && isDebug && getStepIntermediate(step);
          const isTranslationDisabled = step === 2 && !hasTranslation;

          return (
            <div key={step} className="flex flex-col items-center gap-1">
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
                    onClick={() => setExpandedStep(expandedStep === step ? null : step)}
                    className="absolute -right-3 -top-1 rounded-full bg-green-100 p-1 text-green-700 hover:bg-green-200 transition-colors"
                    title={`Download ${STEP_NAMES[step]}`}
                  >
                    <Download className="h-3 w-3" />
                  </button>
                )}
                {isTranslationDisabled && step === 2 && (
                  <div className="absolute -right-3 -top-1 rounded-full bg-gray-200 p-1 text-gray-500">
                    <ChevronDown className="h-3 w-3 opacity-50" />
                  </div>
                )}
              </div>

              {/* Expandable Download Info */}
              {expandedStep === step && canDownload && (
                <div className="absolute top-full mt-1 rounded-md bg-green-50 border border-green-200 p-2 text-xs text-green-800 whitespace-nowrap z-10">
                  <button
                    onClick={() => handleDownloadStep(step)}
                    className="font-medium hover:underline flex items-center gap-1"
                  >
                    <Download className="h-3 w-3" />
                    Download {STEP_NAMES[step]}
                  </button>
                </div>
              )}

              <p className="text-[10px] text-muted-foreground">
                {STEP_NAMES[step]?.split(" ")[0]}
              </p>
            </div>
          );
        })}
      </div>
    </div>
  );
}
