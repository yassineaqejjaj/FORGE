import { EnumIcon } from "@/components/domain/enum-icon";
import { Badge } from "@/components/ui/badge";
import { SimpleTooltip } from "@/components/ui/tooltip";
import { getMeta, SCENARIO_VISIBILITY_META, type ScenarioVisibility } from "@/lib/enums";

export interface VisibilityBadgeProps {
  visibility: ScenarioVisibility | string | null | undefined;
  size?: "sm" | "md";
  /** Icon only (label kept for assistive technologies). */
  iconOnly?: boolean;
  noTooltip?: boolean;
  className?: string;
}

/** Scenario visibility: public (globe) · private (lock) · fresh (sparkles). */
export function VisibilityBadge({ visibility, size = "sm", iconOnly = false, noTooltip = false, className }: VisibilityBadgeProps) {
  const meta = getMeta(SCENARIO_VISIBILITY_META, visibility);
  const badge = (
    <Badge
      tone={meta.tone}
      size={size}
      icon={<EnumIcon name={meta.icon} />}
      className={className}
      aria-label={`Visibilité : ${meta.label}`}
    >
      {iconOnly ? <span className="sr-only">{meta.label}</span> : meta.label}
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
