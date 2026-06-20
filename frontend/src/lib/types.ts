export interface User {
  id: string;
  email: string;
  full_name: string;
  auth_provider: string;
  is_active: boolean;
  tier: string;
  has_openai_key: boolean;
  created_at: string;
}

export interface FeatureFlags {
  requires_api_key: boolean;
}

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  accounts_linked?: boolean;
}

export interface SignupResponse {
  message: string;
  email: string;
  requires_verification: boolean;
}

export interface JobConfig {
  target_duration: number;
  whisper_model: string;
  tts_voice: string;
  tts_model: string;
  language?: string;
  translate_to?: string;
  pad_with_black: boolean;
}

export interface IntermediateFile {
  key: string;
  name: string;
  size_mb: number | null;
  download_url: string | null;
}

export interface Job {
  id: string;
  user_id: string;
  status: string;
  current_step: number;
  current_step_name: string | null;
  progress_pct: number;
  error_message: string | null;
  original_filename: string;
  file_size_bytes: number;
  config: JobConfig;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  expires_at: string | null;
  has_original_in_storage: boolean;
  output_video_key?: string | null;
  intermediate_keys?: Record<string, string> | null;
  intermediate_keys_detailed?: Record<string, IntermediateFile> | null;
}

export interface JobListResponse {
  items: Job[];
  total: number;
  page: number;
  per_page: number;
}

export interface UploadResponse {
  upload_id: string;
  s3_key: string;
  filename: string;
  size: number;
}

export interface ApiKey {
  id: string;
  name: string;
  key_prefix: string;
  is_active: boolean;
  last_used_at: string | null;
  created_at: string;
}

export interface ApiKeyCreated {
  id: string;
  name: string;
  key_prefix: string;
  key: string;
}

export interface UsageSummary {
  tier: string;
  used: number;
  limit: number;
  remaining: number;
}

export interface TierInfo {
  name: string;
  price: number;
  limit: number;
  features: string[];
}

export interface ProgressEvent {
  type: "progress" | "completed" | "failed" | "stopped";
  step?: number;
  step_name?: string;
  progress_pct?: number;
  message?: string;
  output_video_key?: string;
  error?: string;
  input_removed?: boolean;
}
