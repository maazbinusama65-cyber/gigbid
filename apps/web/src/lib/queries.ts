import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, unwrap } from "./client";
import type { ApprovalDecision, OnboardingRequest, UserSettingsUpdate } from "./types";

export interface JobFilters {
  q?: string;
  category?: string;
  min_fit?: number;
  include_skipped?: boolean;
  sort?: "fit" | "posted" | "budget";
}

export const qk = {
  health: ["health"] as const,
  jobs: (f: JobFilters) => ["jobs", f] as const,
  job: (id: string) => ["job", id] as const,
  studio: (id: string) => ["studio", id] as const,
  approvals: ["approvals"] as const,
  pipeline: ["pipeline"] as const,
  threads: ["threads"] as const,
  thread: (id: string) => ["thread", id] as const,
  runs: ["runs"] as const,
  run: (id: string) => ["run", id] as const,
  trace: (id: string) => ["trace", id] as const,
  analytics: ["analytics"] as const,
  settings: ["settings"] as const,
  memory: ["memory"] as const,
  connections: ["connections"] as const,
  onboarding: ["onboarding"] as const,
};

export const useHealth = () =>
  useQuery({
    queryKey: qk.health,
    queryFn: () => unwrap(api.GET("/api/health")),
    refetchInterval: 8000,
    retry: false,
  });

export const useJobs = (f: JobFilters) =>
  useQuery({
    queryKey: qk.jobs(f),
    queryFn: () => unwrap(api.GET("/api/jobs", { params: { query: f } })),
  });

export const useJob = (id: string) =>
  useQuery({
    queryKey: qk.job(id),
    queryFn: () => unwrap(api.GET("/api/jobs/{job_id}", { params: { path: { job_id: id } } })),
  });

export const useStudio = (id: string) =>
  useQuery({
    queryKey: qk.studio(id),
    queryFn: () => unwrap(api.GET("/api/proposals/{job_id}", { params: { path: { job_id: id } } })),
    retry: false,
  });

export const useApprovals = () =>
  useQuery({
    queryKey: qk.approvals,
    queryFn: () => unwrap(api.GET("/api/approvals", { params: { query: {} } })),
  });

export const usePipeline = () =>
  useQuery({ queryKey: qk.pipeline, queryFn: () => unwrap(api.GET("/api/pipeline")) });

export const useThreads = () =>
  useQuery({ queryKey: qk.threads, queryFn: () => unwrap(api.GET("/api/messages")) });

export const useThread = (id: string | undefined) =>
  useQuery({
    queryKey: qk.thread(id ?? ""),
    enabled: !!id,
    queryFn: () => unwrap(api.GET("/api/messages/{thread_id}", { params: { path: { thread_id: id ?? "" } } })),
  });

export const useRuns = () => useQuery({ queryKey: qk.runs, queryFn: () => unwrap(api.GET("/api/runs")) });

export const useRun = (id: string) =>
  useQuery({
    queryKey: qk.run(id),
    queryFn: () => unwrap(api.GET("/api/runs/{run_id}", { params: { path: { run_id: id } } })),
  });

export const useTrace = (id: string, enabled: boolean) =>
  useQuery({
    queryKey: qk.trace(id),
    enabled,
    queryFn: () => unwrap(api.GET("/api/runs/{run_id}/trace", { params: { path: { run_id: id } } })),
  });

export const useAnalytics = () =>
  useQuery({ queryKey: qk.analytics, queryFn: () => unwrap(api.GET("/api/analytics")) });

export const useSettings = () =>
  useQuery({ queryKey: qk.settings, queryFn: () => unwrap(api.GET("/api/settings")) });

export const useMemory = () =>
  useQuery({ queryKey: qk.memory, queryFn: () => unwrap(api.GET("/api/memory")) });

export const useConnections = () =>
  useQuery({ queryKey: qk.connections, queryFn: () => unwrap(api.GET("/api/settings/connections")) });

export const useOnboarding = () =>
  useQuery({ queryKey: qk.onboarding, queryFn: () => unwrap(api.GET("/api/onboarding")) });

/** Everything an approval touches, so a decision refreshes every screen that shows it. */
export function useInvalidateAfterDecision() {
  const qc = useQueryClient();
  return () => {
    for (const key of ["approvals", "pipeline", "jobs", "job", "studio", "runs", "run", "threads", "thread", "analytics", "memory"]) {
      void qc.invalidateQueries({ queryKey: [key] });
    }
  };
}

export function useDecideApproval() {
  const invalidate = useInvalidateAfterDecision();
  return useMutation({
    mutationFn: (v: { approvalId: string; decision: ApprovalDecision }) =>
      unwrap(
        api.POST("/api/approvals/{approval_id}/decision", {
          params: { path: { approval_id: v.approvalId } },
          body: v.decision,
        }),
      ),
    onSettled: invalidate,
  });
}

export function useAnalyzeJob() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (jobId: string) => unwrap(api.POST("/api/jobs/{job_id}/analyze", { params: { path: { job_id: jobId } } })),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["jobs"] });
      void qc.invalidateQueries({ queryKey: ["job"] });
      void qc.invalidateQueries({ queryKey: qk.runs });
    },
  });
}

export function useSkipJob() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { jobId: string; reason: string }) =>
      unwrap(api.POST("/api/jobs/{job_id}/skip", { params: { path: { job_id: v.jobId } }, body: { reason: v.reason } })),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["jobs"] });
      void qc.invalidateQueries({ queryKey: ["job"] });
      void qc.invalidateQueries({ queryKey: qk.analytics });
    },
  });
}

export function useUpdateSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: UserSettingsUpdate) => unwrap(api.PUT("/api/settings", { body })),
    onSuccess: (data) => qc.setQueryData(qk.settings, data),
  });
}

export function useCompleteOnboarding() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: OnboardingRequest) => unwrap(api.PUT("/api/onboarding", { body })),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: qk.onboarding });
      void qc.invalidateQueries({ queryKey: ["me"] });
    },
  });
}
