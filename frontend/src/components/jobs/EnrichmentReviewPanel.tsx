"use client";

import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import api from "@/lib/api";
import type { GenderReviewItem } from "@/lib/types";

type ReviewAction = "confirm" | "override" | "reject";

interface ReviewDecisionState {
  action: ReviewAction;
  gender?: string;
}

interface EnrichmentReviewPanelProps {
  jobId: string;
  onSubmitted: () => void;
}

function formatTimestamp(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds));
  const mins = Math.floor(total / 60);
  const secs = total % 60;
  return `${mins}:${secs.toString().padStart(2, "0")}`;
}

function itemLabel(item: GenderReviewItem): string {
  const presentation = item.presentation;
  if (presentation?.display_label) {
    return presentation.display_label;
  }
  return `Speaker ${item.speaker_id}`;
}

export function EnrichmentReviewPanel({ jobId, onSubmitted }: EnrichmentReviewPanelProps) {
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [queue, setQueue] = useState<GenderReviewItem[]>([]);
  const [decisions, setDecisions] = useState<Record<string, ReviewDecisionState>>({});

  const fetchReview = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await api.get<{ review_queue: GenderReviewItem[] }>(
        `/jobs/${jobId}/enrichment/review`,
      );
      setQueue(data.review_queue || []);
      const initial: Record<string, ReviewDecisionState> = {};
      for (const item of data.review_queue || []) {
        initial[item.speaker_id] = { action: "confirm" };
      }
      setDecisions(initial);
    } catch {
      toast.error("Could not load enrichment review items");
    } finally {
      setLoading(false);
    }
  }, [jobId]);

  useEffect(() => {
    fetchReview();
  }, [fetchReview]);

  const setAction = (speakerId: string, action: ReviewAction, gender?: string) => {
    setDecisions((prev) => ({
      ...prev,
      [speakerId]: { action, gender },
    }));
  };

  const handleSubmit = async () => {
    setSubmitting(true);
    try {
      const payload = {
        decisions: queue.map((item) => {
          const d = decisions[item.speaker_id] || { action: "confirm" as const };
          return {
            speaker_id: item.speaker_id,
            action: d.action,
            gender: d.action === "override" ? d.gender || item.proposed : undefined,
          };
        }),
      };
      await api.post(`/jobs/${jobId}/enrichment/review`, payload);
      toast.success("Review saved — resuming job");
      onSubmitted();
    } catch (err: unknown) {
      const msg =
        err && typeof err === "object" && "response" in err
          ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
          : null;
      toast.error(typeof msg === "string" ? msg : "Failed to submit review");
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) {
    return (
      <div className="rounded-lg border border-amber-300 bg-amber-50 p-4 text-sm dark:border-amber-900 dark:bg-amber-950/30">
        Loading enrichment review…
      </div>
    );
  }

  if (queue.length === 0) {
    return (
      <div className="rounded-lg border p-4 text-sm text-muted-foreground">
        No gender review items pending.
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-amber-300 bg-amber-50 p-4 sm:p-6 dark:border-amber-900 dark:bg-amber-950/30">
      <h3 className="text-sm font-semibold text-amber-950 dark:text-amber-100">
        Enrichment review required
      </h3>
      <p className="mt-1 text-xs text-amber-900/80 dark:text-amber-200/80">
        Confirm or correct low-confidence gender suggestions before recap generation. Each item
        shows who they are in the video — not just a speaker label.
      </p>

      <ul className="mt-4 space-y-3">
        {queue.map((item) => {
          const d = decisions[item.speaker_id] || { action: "confirm" };
          const presentation = item.presentation;
          return (
            <li
              key={item.speaker_id}
              className="rounded-md border bg-background/80 p-3 text-sm"
            >
              <div className="font-medium">
                {itemLabel(item)}: proposed {item.proposed} (
                {(item.confidence * 100).toFixed(0)}% confidence)
              </div>
              {presentation?.sample_quote && (
                <p className="mt-1 text-xs text-muted-foreground">
                  Says: &ldquo;{presentation.sample_quote}&rdquo;
                  {presentation.timestamp_sec != null &&
                    ` · at ${formatTimestamp(presentation.timestamp_sec)}`}
                </p>
              )}
              {item.evidence.length > 0 && (
                <p className="mt-1 text-xs text-muted-foreground/80">
                  Evidence: {item.evidence.join(", ")}
                </p>
              )}
              <div className="mt-2 flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => setAction(item.speaker_id, "confirm")}
                  className={`rounded border px-2 py-1 text-xs ${
                    d.action === "confirm" ? "border-primary bg-primary/10" : ""
                  }`}
                >
                  Confirm
                </button>
                <button
                  type="button"
                  onClick={() => setAction(item.speaker_id, "reject")}
                  className={`rounded border px-2 py-1 text-xs ${
                    d.action === "reject" ? "border-primary bg-primary/10" : ""
                  }`}
                >
                  Reject (unknown)
                </button>
                <label className="flex items-center gap-1 text-xs">
                  Override:
                  <select
                    className="rounded border bg-background px-1 py-0.5"
                    value={d.action === "override" ? d.gender || item.proposed : ""}
                    onChange={(e) => {
                      if (e.target.value) {
                        setAction(item.speaker_id, "override", e.target.value);
                      }
                    }}
                  >
                    <option value="">—</option>
                    <option value="female">female</option>
                    <option value="male">male</option>
                    <option value="unknown">unknown</option>
                  </select>
                </label>
              </div>
            </li>
          );
        })}
      </ul>

      <button
        type="button"
        disabled={submitting}
        onClick={handleSubmit}
        className="mt-4 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50"
      >
        {submitting ? "Submitting…" : "Submit review and continue"}
      </button>
    </div>
  );
}
