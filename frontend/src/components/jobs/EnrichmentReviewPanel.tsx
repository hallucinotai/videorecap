"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import api from "@/lib/api";
import type { GenderReviewItem } from "@/lib/types";

type ReviewAction = "confirm" | "override" | "reject";

interface ReviewDecisionState {
  action: ReviewAction;
  gender?: string;
  speaker_confirmed?: string;
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

function itemKey(item: GenderReviewItem): string {
  if ((item.type || "gender") === "attribution") {
    return `attribution:${item.utterance_id || item.presentation?.utterance_id || item.speaker_id}`;
  }
  return `gender:${item.speaker_id}`;
}

function itemLabel(item: GenderReviewItem): string {
  const presentation = item.presentation;
  if (presentation?.display_label) {
    return presentation.display_label;
  }
  if ((item.type || "gender") === "attribution") {
    return `Utterance ${item.utterance_id || "?"}`;
  }
  return `Speaker ${item.speaker_id}`;
}

export function EnrichmentReviewPanel({ jobId, onSubmitted }: EnrichmentReviewPanelProps) {
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [queue, setQueue] = useState<GenderReviewItem[]>([]);
  const [speakerIds, setSpeakerIds] = useState<string[]>([]);
  const [decisions, setDecisions] = useState<Record<string, ReviewDecisionState>>({});

  const fetchReview = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await api.get<{
        review_queue: GenderReviewItem[];
        speaker_profiles?: Record<string, unknown>;
      }>(`/jobs/${jobId}/enrichment/review`);
      const items = data.review_queue || [];
      setQueue(items);
      const profiles = data.speaker_profiles || {};
      const ids = Object.keys(profiles).sort();
      setSpeakerIds(ids.length > 0 ? ids : [...new Set(items.map((i) => i.speaker_id))].sort());
      const initial: Record<string, ReviewDecisionState> = {};
      for (const item of items) {
        initial[itemKey(item)] = { action: "confirm" };
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

  const setAction = (key: string, action: ReviewAction, extra?: Partial<ReviewDecisionState>) => {
    setDecisions((prev) => ({
      ...prev,
      [key]: { action, ...extra },
    }));
  };

  const genderItems = useMemo(
    () => queue.filter((i) => (i.type || "gender") === "gender"),
    [queue],
  );
  const attributionItems = useMemo(
    () => queue.filter((i) => i.type === "attribution"),
    [queue],
  );

  const handleSubmit = async () => {
    setSubmitting(true);
    try {
      const payload = {
        decisions: queue.map((item) => {
          const key = itemKey(item);
          const d = decisions[key] || { action: "confirm" as const };
          const itemType = item.type || "gender";
          if (itemType === "attribution") {
            return {
              type: "attribution",
              utterance_id: item.utterance_id || item.presentation?.utterance_id,
              speaker_id: item.speaker_id,
              action: d.action,
              speaker_confirmed:
                d.action === "override"
                  ? d.speaker_confirmed || item.proposed
                  : undefined,
            };
          }
          return {
            type: "gender",
            speaker_id: item.speaker_id,
            action: d.action,
            gender: d.action === "override" ? d.gender || item.proposed : undefined,
          };
        }),
      };
      await api.post(`/jobs/${jobId}/enrichment/review`, payload);
      toast.success("Review saved — job complete");
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
        No enrichment review items pending.
      </div>
    );
  }

  const renderGenderItem = (item: GenderReviewItem) => {
    const key = itemKey(item);
    const d = decisions[key] || { action: "confirm" };
    const presentation = item.presentation;
    return (
      <li key={key} className="rounded-md border bg-background/80 p-3 text-sm">
        <div className="flex gap-3">
          {presentation?.thumbnail_url && (
            <img
              src={presentation.thumbnail_url}
              alt=""
              className="h-16 w-16 shrink-0 rounded-md border object-cover"
            />
          )}
          <div className="min-w-0 flex-1">
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
                onClick={() => setAction(key, "confirm")}
                className={`rounded border px-2 py-1 text-xs ${
                  d.action === "confirm" ? "border-primary bg-primary/10" : ""
                }`}
              >
                Confirm
              </button>
              <button
                type="button"
                onClick={() => setAction(key, "reject")}
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
                      setAction(key, "override", { gender: e.target.value });
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
          </div>
        </div>
      </li>
    );
  };

  const renderAttributionItem = (item: GenderReviewItem) => {
    const key = itemKey(item);
    const d = decisions[key] || { action: "confirm" };
    const presentation = item.presentation;
    const overrideOptions = speakerIds.length > 0 ? speakerIds : [item.speaker_id, item.proposed].filter(Boolean);
    return (
      <li key={key} className="rounded-md border bg-background/80 p-3 text-sm">
        <div className="min-w-0 flex-1">
          <div className="font-medium">
            {itemLabel(item)}: diarized as {item.speaker_id}, proposed speaker {item.proposed} (
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
              onClick={() => setAction(key, "confirm")}
              className={`rounded border px-2 py-1 text-xs ${
                d.action === "confirm" ? "border-primary bg-primary/10" : ""
              }`}
            >
              Confirm proposed
            </button>
            <button
              type="button"
              onClick={() => setAction(key, "reject")}
              className={`rounded border px-2 py-1 text-xs ${
                d.action === "reject" ? "border-primary bg-primary/10" : ""
              }`}
            >
              Keep diarized ({item.speaker_id})
            </button>
            <label className="flex items-center gap-1 text-xs">
              Override speaker:
              <select
                className="rounded border bg-background px-1 py-0.5"
                value={d.action === "override" ? d.speaker_confirmed || item.proposed : ""}
                onChange={(e) => {
                  if (e.target.value) {
                    setAction(key, "override", { speaker_confirmed: e.target.value });
                  }
                }}
              >
                <option value="">—</option>
                {overrideOptions.map((sid) => (
                  <option key={sid} value={sid}>
                    {sid}
                  </option>
                ))}
              </select>
            </label>
          </div>
        </div>
      </li>
    );
  };

  return (
    <div className="rounded-lg border border-amber-300 bg-amber-50 p-4 sm:p-6 dark:border-amber-900 dark:bg-amber-950/30">
      <h3 className="text-sm font-semibold text-amber-950 dark:text-amber-100">
        Enrichment review required
      </h3>
      <p className="mt-1 text-xs text-amber-900/80 dark:text-amber-200/80">
        Confirm or correct pending gender and speaker-attribution suggestions to finish enrichment.
      </p>

      {genderItems.length > 0 && (
        <div className="mt-4">
          <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-amber-900/70 dark:text-amber-200/70">
            Gender
          </h4>
          <ul className="space-y-3">{genderItems.map(renderGenderItem)}</ul>
        </div>
      )}

      {attributionItems.length > 0 && (
        <div className="mt-4">
          <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-amber-900/70 dark:text-amber-200/70">
            Speaker attribution
          </h4>
          <ul className="space-y-3">{attributionItems.map(renderAttributionItem)}</ul>
        </div>
      )}

      <button
        type="button"
        disabled={submitting}
        onClick={handleSubmit}
        className="mt-4 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50"
      >
        {submitting ? "Submitting…" : "Submit review and complete"}
      </button>
    </div>
  );
}
