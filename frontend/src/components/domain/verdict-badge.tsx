import { EnumIcon } from "@/components/domain/enum-icon";
import { Badge } from "@/components/ui/badge";
import { SimpleTooltip } from "@/components/ui/tooltip";
import { getMeta, RECOMMENDATION_META, VERDICT_META, type Recommendation, type Verdict } from "@/lib/enums";

export interface VerdictBadgeProps {
  verdict: Verdict | string | null | undefined;
  size?: "sm" | "md";
  className?: string;
}

/** Comparison verdict of a candidate vs its baseline (better / worse / equivalent / inconclusive). */
export function VerdictBadge({ verdict, size = "sm", className }: VerdictBadgeProps) {
  const meta = getMeta(VERDICT_META, verdict);
  return (
    <Badge tone={meta.tone} size={size} icon={<EnumIcon name={meta.icon} />} className={className} aria-label={`Verdict : ${meta.label}`}>
      {meta.label}
    </Badge>
  );
}

export interface RecommendationBadgeProps {
  recommendation: Recommendation | string | null | undefined;
  size?: "sm" | "md";
  /** Solid pill (experiment header, CI gate). */
  emphasis?: boolean;
  noTooltip?: boolean;
  className?: string;
}

/** Overall experiment recommendation: ship / ship with caution / do not ship / inconclusive. */
export function RecommendationBadge({ recommendation, size = "md", emphasis = false, noTooltip = false, className }: RecommendationBadgeProps) {
  const meta = getMeta(RECOMMENDATION_META, recommendation);
  const badge = (
    <Badge
      tone={meta.tone}
      size={size}
      variant={emphasis ? "solid" : "soft"}
      icon={<EnumIcon name={meta.icon} />}
      className={className}
      aria-label={`Recommandation : ${meta.label}`}
    >
      {meta.label}
    </Badge>
  );
  if (noTooltip || !meta.description) return badge;
  return (
    <SimpleTooltip content={meta.description}>
      <span className="inline-flex">
        {badge}
      </span>
    </SimpleTooltip>
  );
}
