import { EnumIcon } from "@/components/domain/enum-icon";
import { Badge, type BadgeProps } from "@/components/ui/badge";
import { SimpleTooltip } from "@/components/ui/tooltip";
import {
  ACTOR_TYPE_META,
  ADAPTER_KIND_META,
  AGGREGATION_METHOD_META,
  CALIBRATION_STATUS_META,
  CONTEXT_SOURCE_META,
  DATASET_KIND_META,
  DIFFICULTY_META,
  EVALUATOR_KIND_META,
  EXPERIMENT_ARM_META,
  FEEDBACK_SCOPE_META,
  GATE_ACTION_META,
  getMeta,
  JOB_KIND_META,
  JUDGE_PROVIDER_META,
  PRIORITY_META,
  PROVIDER_KIND_META,
  RECOMMENDATION_CATEGORY_META,
  REGRESSION_SEVERITY_META,
  ROLE_META,
  RULE_TYPE_META,
  RUN_ORIGIN_META,
  SCORE_SOURCE_META,
  TRACE_EVENT_SOURCE_META,
  TRACE_EVENT_TYPE_META,
  type EnumMeta,
} from "@/lib/enums";

export interface EnumBadgeProps extends Omit<BadgeProps, "tone" | "children"> {
  meta: Record<string, EnumMeta>;
  value: string | null | undefined;
  /** Show the enum icon when it has one (default true). */
  withIcon?: boolean;
  /** Show the description in a tooltip (default true when the value has one). */
  withTooltip?: boolean;
}

/** Generic badge for any `*_META` enum record (French label, tone, icon, tooltip). */
export function EnumBadge({ meta, value, withIcon = true, withTooltip = true, ...props }: EnumBadgeProps) {
  const m = getMeta(meta, value);
  const badge = (
    <Badge tone={m.tone} icon={withIcon && m.icon ? <EnumIcon name={m.icon} /> : undefined} {...props}>
      {m.label}
    </Badge>
  );
  if (!withTooltip || !m.description) return badge;
  return (
    <SimpleTooltip content={m.description}>
      <span className="inline-flex max-w-full">
        {badge}
      </span>
    </SimpleTooltip>
  );
}

export type ValueBadgeProps = Omit<EnumBadgeProps, "meta">;

export const RoleBadge = (props: ValueBadgeProps) => <EnumBadge meta={ROLE_META} {...props} />;
export const ActorTypeBadge = (props: ValueBadgeProps) => <EnumBadge meta={ACTOR_TYPE_META} {...props} />;
export const AdapterKindBadge = (props: ValueBadgeProps) => <EnumBadge meta={ADAPTER_KIND_META} {...props} />;
export const ProviderKindBadge = (props: ValueBadgeProps) => <EnumBadge meta={PROVIDER_KIND_META} {...props} />;
export const ContextSourceBadge = (props: ValueBadgeProps) => (
  <EnumBadge meta={CONTEXT_SOURCE_META} variant="outline" {...props} />
);
export const DifficultyBadge = (props: ValueBadgeProps) => <EnumBadge meta={DIFFICULTY_META} dot {...props} />;
export const DatasetKindBadge = (props: ValueBadgeProps) => <EnumBadge meta={DATASET_KIND_META} {...props} />;
export const RunOriginBadge = (props: ValueBadgeProps) => <EnumBadge meta={RUN_ORIGIN_META} variant="outline" {...props} />;
export const ExperimentArmBadge = (props: ValueBadgeProps) => <EnumBadge meta={EXPERIMENT_ARM_META} {...props} />;
export const TraceEventTypeBadge = (props: ValueBadgeProps) => <EnumBadge meta={TRACE_EVENT_TYPE_META} {...props} />;
export const TraceEventSourceBadge = (props: ValueBadgeProps) => (
  <EnumBadge meta={TRACE_EVENT_SOURCE_META} variant="outline" {...props} />
);
export const EvaluatorKindBadge = (props: ValueBadgeProps) => <EnumBadge meta={EVALUATOR_KIND_META} {...props} />;
export const ScoreSourceBadge = (props: ValueBadgeProps) => <EnumBadge meta={SCORE_SOURCE_META} {...props} />;
export const RuleTypeBadge = (props: ValueBadgeProps) => <EnumBadge meta={RULE_TYPE_META} variant="outline" {...props} />;
export const JudgeProviderBadge = (props: ValueBadgeProps) => <EnumBadge meta={JUDGE_PROVIDER_META} {...props} />;
export const AggregationMethodBadge = (props: ValueBadgeProps) => (
  <EnumBadge meta={AGGREGATION_METHOD_META} variant="outline" {...props} />
);
export const GateActionBadge = (props: ValueBadgeProps) => <EnumBadge meta={GATE_ACTION_META} {...props} />;
export const RecommendationCategoryBadge = (props: ValueBadgeProps) => (
  <EnumBadge meta={RECOMMENDATION_CATEGORY_META} {...props} />
);
export const PriorityBadge = (props: ValueBadgeProps) => <EnumBadge meta={PRIORITY_META} {...props} />;
export const FeedbackScopeBadge = (props: ValueBadgeProps) => <EnumBadge meta={FEEDBACK_SCOPE_META} {...props} />;
export const RegressionSeverityBadge = (props: ValueBadgeProps) => (
  <EnumBadge meta={REGRESSION_SEVERITY_META} dot {...props} />
);
export const CalibrationStatusBadge = (props: ValueBadgeProps) => (
  <EnumBadge meta={CALIBRATION_STATUS_META} dot {...props} />
);
export const JobKindBadge = (props: ValueBadgeProps) => <EnumBadge meta={JOB_KIND_META} variant="outline" {...props} />;
