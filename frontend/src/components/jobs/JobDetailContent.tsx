"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { Download, Trash2, RotateCcw, Square, X } from "lucide-react";
import { useJobs } from "@/hooks/useJobs";
import { useJobProgress } from "@/hooks/useJobProgress";
import { formatDate, formatFileSize, statusColor } from "@/lib/utils";
import type { Job } from "@/lib/types";
import api from "@/lib/api";
import { StepProgressWithDownloads } from "./StepProgressWithDownloads";

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

export interface JobDetailContentProps {
  jobId: string;
  /** When set, shows a close control (e.g. modal). */
  onClose?: () => void;
  /** Called after a successful delete; if omitted, navigates to /jobs. */
  onAfterDelete?: () => void;
}

export function JobDetailContent({
  jobId,
  onClose,
  onAfterDelete,
}: JobDetailContentProps) {
  const [job, setJob] = useState<Job | null>(null);
  const [resuming, setResuming] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [activityLog, setActivityLog] = useState<
    { time: string; message: string; step: number }[]
  >([]);
  const logEndRef = useRef<HTMLDivElement>(null);
  const inputRemovalToastRef = useRef(false);
  const { getJob, deleteJob, resumeJob, stopJob } = useJobs();
  const progress = useJobProgress(
    job?.status === "processing" || job?.status === "pending" ? jobId : null
  );
  const router = useRouter();

  const fetchJob = useCallback(async () => {
    const data = await getJob(jobId);
    setJob(data);
  }, [jobId, getJob]);

  useEffect(() => {
    inputRemovalToastRef.current = false;
  }, [jobId]);

  useEffect(() => {
    fetchJob();
  }, [fetchJob]);

  useEffect(() => {
    if (progress?.type === "completed" || progress?.type === "failed" || progress?.type === "stopped") {
      fetchJob();
    }
    if (progress?.message) {
      const msg = progress.message;
      const step = progress.step ?? 0;
      setActivityLog((prev) => {
        if (prev.length > 0 && prev[prev.length - 1].message === msg) return prev;
        return [...prev, { time: new Date().toLocaleTimeString(), message: msg, step }];
      });
    }
  }, [progress, fetchJob]);

  useEffect(() => {
    if (
      progress?.type === "completed" &&
      progress.input_removed &&
      !inputRemovalToastRef.current
    ) {
      inputRemovalToastRef.current = true;
      toast.info("Original upload removed from our servers", {
        description:
          "We automatically delete your uploaded video after the recap is ready. Your recap is still available to download until it expires.",
        duration: 10_000,
      });
    }
  }, [progress]);

  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [activityLog]);

  const isDebug = typeof window !== "undefined" && window.__meta__?.debug === true;

  const handleFileDownload = async (endpoint: string, baseFilename: string) => {
    try {
      const response = await api.get(endpoint, { responseType: "blob" });
      const disposition = response.headers["content-disposition"] || "";
      const match = disposition.match(/filename="?(.+?)"?$/);
      const filename = match?.[1] || `${baseFilename}`;
      const url = URL.createObjectURL(response.data);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      a.click();
      URL.revokeObjectURL(url);
      // Success! File downloaded
      toast.success(`Downloaded ${filename.split("_")[1] || baseFilename}`);
    } catch {
      toast.error("Download not available");
    }
  };

  const handleDownload = async () => {
    await handleFileDownload(`/jobs/${jobId}/download`, "recap_video.mp4");
  };

  const handleDownloadNarration = async () => {
    await handleFileDownload(`/jobs/${jobId}/debug/tts-audio`, "narration.mp3");
  };

  const handleDelete = async () => {
    if (!confirm("Delete this job and all associated files?")) return;
    try {
      await deleteJob(jobId);
      toast.success("Job deleted");
      if (onAfterDelete) onAfterDelete();
      else router.push("/jobs");
    } catch {
      toast.error("Failed to delete job");
    }
  };

  const handleResume = async () => {
    setResuming(true);
    try {
      const updated = await resumeJob(jobId);
      setJob(updated);
      toast.success(
        `Resuming from step ${updated.current_step}: ${STEP_NAMES[updated.current_step] || ""}`,
      );
    } catch {
      toast.error("Failed to resume job");
    } finally {
      setResuming(false);
    }
  };

  const handleStop = async () => {
    setStopping(true);
    try {
      const updated = await stopJob(jobId);
      setJob(updated);
      toast.success("Job stopped. You can resume it later.");
    } catch {
      toast.error("Failed to stop job");
    } finally {
      setStopping(false);
    }
  };

  if (!job) {
    return <div className="p-8 text-center text-muted-foreground">Loading...</div>;
  }

  const activeStep = progress?.step ?? job.current_step;
  const activePct = progress?.progress_pct ?? job.progress_pct;
  const activeMessage = progress?.message ?? job.current_step_name;

  return (
    <div>
      {job.status === "completed" && job.has_original_in_storage === false && (
        <div className="mb-6 rounded-lg border border-sky-200 bg-sky-50 px-4 py-3 text-sm text-sky-900 dark:border-sky-900 dark:bg-sky-950/40 dark:text-sky-100">
          <p className="font-medium">Original file no longer stored</p>
          <p className="mt-1 text-sky-800/90 dark:text-sky-200/90">
            Your uploaded video was removed from our storage after this recap finished successfully. Your
            recap file stays available to download
            {job.expires_at ? ` until ${formatDate(job.expires_at)}` : ""}.
          </p>
        </div>
      )}

      <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <h2 className="break-words text-xl font-bold sm:text-2xl">{job.original_filename}</h2>
        <div className="flex shrink-0 flex-wrap items-center justify-end gap-2">
          {(job.status === "processing" || job.status === "pending") && (
            <button
              type="button"
              onClick={handleStop}
              disabled={stopping}
              className="flex items-center gap-1 rounded-md bg-orange-600 px-3 py-2 text-sm text-white hover:bg-orange-700 disabled:opacity-50 sm:px-4"
            >
              <Square className="h-3.5 w-3.5 fill-current" />
              {stopping ? "Stopping..." : "Stop"}
            </button>
          )}
          {(job.status === "failed" || job.status === "stopped") && (
            <button
              type="button"
              onClick={handleResume}
              disabled={resuming}
              className="flex items-center gap-1 rounded-md bg-blue-600 px-3 py-2 text-sm text-white hover:bg-blue-700 disabled:opacity-50 sm:px-4"
            >
              <RotateCcw className={`h-4 w-4 ${resuming ? "animate-spin" : ""}`} />
              {resuming ? "Resuming..." : `Resume from Step ${job.current_step}`}
            </button>
          )}
          {job.status === "completed" && (
            <button
              type="button"
              onClick={handleDownload}
              className="flex items-center gap-1 rounded-md bg-primary px-3 py-2 text-sm text-primary-foreground hover:opacity-90 sm:px-4"
            >
              <Download className="h-4 w-4" />
              Download
            </button>
          )}
          {job.status === "completed" && isDebug && (
            <button
              type="button"
              onClick={handleDownloadNarration}
              className="flex items-center gap-1 rounded-md border border-primary/30 px-3 py-2 text-sm text-primary hover:bg-primary/10 sm:px-4"
            >
              <Download className="h-4 w-4" />
              Narration
            </button>
          )}
          <button
            type="button"
            onClick={handleDelete}
            className="flex items-center gap-1 rounded-md border px-3 py-2 text-sm text-destructive hover:bg-destructive/10 sm:px-4"
          >
            <Trash2 className="h-4 w-4" />
            Delete
          </button>
          {onClose && (
            <button
              type="button"
              onClick={onClose}
              className="rounded-md border p-2 hover:bg-secondary"
              aria-label="Close"
            >
              <X className="h-5 w-5" />
            </button>
          )}
        </div>
      </div>

      <div className="mb-6 rounded-lg border p-4 sm:p-6">
        <div className="mb-4 flex items-center justify-between gap-2">
          <span
            className={`rounded-full px-3 py-1 text-sm font-medium ${statusColor(job.status)}`}
          >
            {job.status}
          </span>
          <span className="text-sm text-muted-foreground">
            {formatFileSize(job.file_size_bytes)}
          </span>
        </div>

        {(job.status === "processing" || job.status === "pending") && (
          <div>
            <div className="mb-2 h-3 rounded-full bg-secondary">
              <div
                className="h-3 rounded-full bg-blue-600 transition-all duration-500"
                style={{ width: `${activePct}%` }}
              />
            </div>
            <div className="flex justify-between text-sm">
              <span className="text-muted-foreground">{activeMessage || "Waiting..."}</span>
              <span className="font-medium">{Math.round(activePct)}%</span>
            </div>

            <StepProgressWithDownloads
              activeStep={activeStep}
              job={job}
              isDebug={isDebug}
              onDownload={handleFileDownload}
            />
          </div>
        )}

        {(job.status === "failed" || job.status === "stopped") && (
          <div>
            {job.status === "failed" && job.error_message && (
              <div className="rounded-md bg-red-50 p-4 text-sm text-red-800 dark:bg-red-950/30 dark:text-red-400">
                {job.error_message}
              </div>
            )}
            <div className={job.error_message && job.status === "failed" ? "mt-4" : ""}>
              <p className="mb-2 text-sm text-muted-foreground">
                {job.status === "stopped" ? "Stopped" : "Failed"} at step {job.current_step} of 7:{" "}
                {STEP_NAMES[job.current_step] || "Unknown"}
              </p>
              <StepProgressWithDownloads
                activeStep={job.current_step}
                job={job}
                isDebug={isDebug}
                onDownload={handleFileDownload}
              />
            </div>
          </div>
        )}

        {job.status === "completed" && (
          <div>
            <p className="mb-3 text-sm text-muted-foreground">
              All steps completed successfully
            </p>
            <StepProgressWithDownloads
              activeStep={7}
              job={job}
              isDebug={isDebug}
              onDownload={handleFileDownload}
            />
          </div>
        )}
      </div>

      {activityLog.length > 0 && (
        <div className="mb-6 rounded-lg border p-4 sm:p-6">
          <h3 className="mb-3 text-sm font-semibold">Activity Log</h3>
          <div className="max-h-40 overflow-y-auto rounded-md bg-muted/30 p-3 font-mono text-xs leading-relaxed">
            {activityLog.map((entry, i) => (
              <div key={i} className="flex gap-3 py-0.5">
                <span className="shrink-0 text-muted-foreground">{entry.time}</span>
                <span className="shrink-0 text-blue-500">[Step {entry.step}]</span>
                <span>{entry.message}</span>
              </div>
            ))}
            <div ref={logEndRef} />
          </div>
        </div>
      )}

      <div className="rounded-lg border p-4 sm:p-6">
        <h3 className="mb-4 font-semibold">Details</h3>
        <dl className="grid grid-cols-1 gap-4 text-sm sm:grid-cols-2">
          <div>
            <dt className="text-muted-foreground">Created</dt>
            <dd>{formatDate(job.created_at)}</dd>
          </div>
          {job.started_at && (
            <div>
              <dt className="text-muted-foreground">Started</dt>
              <dd>{formatDate(job.started_at)}</dd>
            </div>
          )}
          {job.completed_at && (
            <div>
              <dt className="text-muted-foreground">Completed</dt>
              <dd>{formatDate(job.completed_at)}</dd>
            </div>
          )}
          {job.expires_at && (
            <div>
              <dt className="text-muted-foreground">Expires</dt>
              <dd>{formatDate(job.expires_at)}</dd>
            </div>
          )}
          <div>
            <dt className="text-muted-foreground">Target Duration</dt>
            <dd>{job.config.target_duration}s</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">Voice</dt>
            <dd>{job.config.tts_voice}</dd>
          </div>
        </dl>
      </div>
    </div>
  );
}
