export type MovementStage = {
  kind?: string;
  name: string;
  start: number;
  end: number;
  resources?: string[];
  route?: {
    edges: string[];
    metres: number;
    minutes: number;
    loaded: boolean;
    source: string;
    target: string;
  } | null;
};
export type Location = {
  id: string;
  kind: string;
  zone: string;
  capacity: number;
  block: string;
  x: number;
  y: number;
  label: string;
};
export type Equipment = {
  within_shift?: boolean;
  id: string;
  kind: string;
  zone: string;
  status: string;
  job_id: string | null;
  x: number;
  y: number;
};
export type Cargo = {
  custody?: { kind: string; id: string };
  id: string;
  visit_id: string;
  location_id: string | null;
  tier: number;
  flow: string;
  commitment_id: string | null;
  released: boolean;
  hold_reason: string | null;
  weight_t: number;
  job_id: string | null;
};
export type Job = {
  stage_history?: {
    name: string;
    start: number;
    end: number | null;
    resources: string[];
  }[];
  movement_stages?: MovementStage[];
  stage_index?: number;
  stage_remaining?: number;
  waiting_reason?: string;
  movement_preview?: { stages: MovementStage[] };
  movement_error?: string;
  placement_basis?: {
    proposal_id: string;
    revision: number;
    destination: string;
    method: string;
  };
  id: string;
  container_id: string;
  source_id: string;
  target_id: string;
  kind: string;
  equipment_id: string;
  status: string;
  duration: number;
  remaining: number;
  deadline: number;
  dependencies: string[];
  started_at: number | null;
  completed_at: number | null;
  resources: string[];
  blockers: string[];
  purpose: string;
  visit_id: string;
  commitment_id: string | null;
  requirements: Requirement[];
  predecessors: {
    id: string;
    reason: string;
    origin: string;
    kind: string;
    basis_revision: number;
  }[];
  successors: string[];
  stages: { name: string; location: string; capability: string }[];
  slack: number;
  risk: string;
};
export type Commitment = {
  id: string;
  kind: string;
  location_id: string;
  cutoff: number;
  capacity: number;
  arrival: number;
  status: string;
};
export type Metrics = {
  total: number;
  on_time: number;
  missed: number;
  pending: number;
  completed_moves: number;
  rehandles: number;
  travel_minutes: number;
  mean_wait: number;
  lateness: number;
};
export type State = {
  movement?: {
    version: string;
    digest: string;
    nodes: { id: string; x: number; y: number }[];
    edges: {
      id: string;
      source: string;
      target: string;
      metres: number;
      loaded_mpm: number;
      closed: boolean;
    }[];
  };
  availability?: {
    equipment_id: string;
    start_minute: number;
    end_minute: number;
  }[];
  schedule?: import("./ScheduleRecovery").ApprovedSchedule;
  dataset?: {
    pack_id: string;
    title: string;
    digest: string;
    shift_start: string;
  };
  input_provenance?: Record<
    string,
    {
      source: string;
      observed_minute: number;
      received_minute: number;
      known_revision: number;
      value: unknown;
    }
  >;
  relationships: {
    nodes: { id: string; kind: string; label: string }[];
    edges: Edge[];
  };
  provenance: {
    mode: string;
    source: string;
    recorded_revision: number;
    observed_minute: number;
    resource_model: string;
    warning: string;
  };
  parent?: { run_id: string; revision: number } | null;
  revision: number;
  minute: number;
  seed: number;
  policy: string;
  running: boolean;
  speed: number;
  profile: string;
  locations: Location[];
  equipment: Equipment[];
  containers: Cargo[];
  jobs: Job[];
  commitments: Commitment[];
  metrics: Metrics;
  plan_id: string | null;
  observations: Observation[];
};
export type Observation = {
  entity_id: string;
  valid_minute: number;
  recorded_minute: number;
  revision: number;
  value: string;
  source: string;
  supersedes: number | null;
};
export type Event = {
  id: number;
  revision: number;
  kind: string;
  entity_id: string;
  valid_minute: number;
  recorded_at: string;
  command_id: string | null;
  payload: { message: string; job_id?: string; job_ids?: string[] };
};
export type Candidate = {
  policy: string;
  title: string;
  metrics: Metrics;
  interval: number[];
  delta_on_time: number;
  plan_id?: string;
  changes: {
    job_id: string;
    container_id?: string;
    commitment_id?: string;
    before: string;
    after: string;
  }[];
  unresolved: { job_id: string; reasons: string[] }[];
  explanation: string;
  curve: ({ minute: number } & Metrics)[];
};
export type Experiment = {
  id: string;
  base_revision: number;
  status: string;
  progress: number;
  manifest: { seeds: number[]; horizon: number; calibration: string };
  result: null | {
    candidates: Candidate[];
    recommended: string;
    warning: string;
    elapsed_seconds: number;
  };
  error: string | null;
};
export type CommandResult = {
  id: string;
  status: string;
  payload: { action: string; entity_id?: string; plan_id?: string };
  result: { error?: string; revision?: number } | null;
};
export type Source = {
  id: string;
  title: string;
  source: string;
  review_status: string;
  executable: boolean;
  body: string;
};
export const clock = (m: number) =>
  `${String(8 + Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;

export type Requirement = {
  role: string;
  capability: string;
  assigned: string | null;
  eligible: string[];
  available: string[];
  reserved: string[];
};
export type Edge = {
  source: string;
  target: string;
  relation: string;
  state: string;
  reason?: string;
  origin?: string;
  basis_revision?: number;
};
export type AccessProposal = {
  job_id: string;
  base_revision: number;
  token: string;
  moves: {
    container_id: string;
    source_id: string;
    target_id: string;
    equipment_id: string;
    reason: string;
  }[];
  assumptions: string[];
};
export type InputRecord = {
  id: number;
  source: string;
  source_event_id: string;
  event_time: number;
  recorded_at: string;
  status: string;
  reason: string | null;
  payload: { entity_id: string; value: string };
};
