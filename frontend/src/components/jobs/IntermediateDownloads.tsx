"use client";

import { useState } from "react";
import { Download, ChevronDown, Lock, Info } from "lucide-react";
import { toast } from "sonner";
import type { Job } from "@/lib/types";

const STEP_NAME = "Transcribe & enrich";
const STEP_DESCRIPTION =
  "Transcribe video, run enrichment layers (L1–L4), and inject scene understanding into L4";

interface IntermediateDownloadsProps {
  job: Job;
  activeStep: number;
  onDownload: (endpoint: string, filename: string) => Promise<void>;
}

export function IntermediateDownloads({
  job,
  activeStep,
  onDownload,
}: IntermediateDownloadsProps) {
  const [expandedDetails, setExpandedDetails] = useState(false);

  if (!job.intermediate_keys_detailed) {
    return null;
  }

  const intermediate = job.intermediate_keys_detailed?.["transcription"];
  const status: "completed" | "active" | "pending" =
    job.status === "completed" || activeStep > 1
      ? "completed"
      : activeStep === 1
        ? "active"
        : "pending";
  const canDownload = !!intermediate?.download_url;

  const handleDownload = async () => {
    if (!intermediate?.download_url) {
      toast.error("Download link not available");
      return;
    }
    try {
      await onDownload(intermediate.download_url, `${job.id}_transcription`);
    } catch {
      toast.error("Failed to download transcription");
    }
  };

  return (
    <div className="rounded-lg border border-gray-200 p-4 sm:p-6">
      <h3 className="mb-1 text-lg font-semibold">Step 1 outputs</h3>
      <p className="mb-4 text-sm text-gray-600">
        Download transcription and enrichment artifacts from Step 1.
      </p>

      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        <div
          className={`rounded-lg border-2 p-4 transition-all ${
            status === "completed"
              ? "border-green-300 bg-green-50"
              : status === "active"
                ? "border-blue-300 bg-blue-50"
                : "border-gray-300 bg-gray-50"
          }`}
        >
          <div className="mb-3 flex items-center gap-2">
            <div
              className={`flex h-8 w-8 items-center justify-center rounded-full font-bold text-white ${
                status === "completed"
                  ? "bg-green-500"
                  : status === "active"
                    ? "bg-blue-500"
                    : "bg-gray-400"
              }`}
            >
              {status === "completed" ? "✓" : status === "active" ? "•" : "○"}
            </div>
            <h4 className="font-semibold text-gray-900">Step 1: {STEP_NAME}</h4>
          </div>

          <p className="mb-3 text-xs text-gray-600">{STEP_DESCRIPTION}</p>

          {canDownload && intermediate && (
            <>
              <div className="mb-3 space-y-1 text-xs text-gray-600">
                <p>
                  <strong>File:</strong> transcription.json
                </p>
                {intermediate.size_mb != null && (
                  <p>
                    <strong>Size:</strong> {intermediate.size_mb} MB
                  </p>
                )}
              </div>

              {expandedDetails && (
                <div className="mb-3 rounded-md bg-gray-100 p-2 text-xs text-gray-700">
                  <p className="mb-1 break-all">
                    <strong>S3 Key:</strong> {intermediate.key}
                  </p>
                  <p>
                    <strong>Type:</strong> transcription
                  </p>
                </div>
              )}

              <div className="flex flex-col gap-2">
                <button
                  type="button"
                  onClick={handleDownload}
                  className="flex items-center justify-center gap-2 rounded-md bg-green-100 px-3 py-2 text-sm font-medium text-green-700 hover:bg-green-200"
                >
                  <Download className="h-4 w-4" />
                  Download
                </button>
                <button
                  type="button"
                  onClick={() => setExpandedDetails(!expandedDetails)}
                  className="flex items-center justify-center gap-1 rounded-md border border-gray-300 px-3 py-1 text-xs text-gray-600 hover:bg-gray-100"
                >
                  <Info className="h-3 w-3" />
                  {expandedDetails ? "Hide" : "Details"}
                  <ChevronDown
                    className={`h-3 w-3 transition-transform ${
                      expandedDetails ? "rotate-180" : ""
                    }`}
                  />
                </button>
              </div>
            </>
          )}

          {!canDownload && (
            <button
              type="button"
              disabled
              className="w-full rounded-md bg-gray-100 px-3 py-2 text-sm font-medium text-gray-500"
            >
              <Lock className="mr-1 inline h-4 w-4" />
              Not Available Yet
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
