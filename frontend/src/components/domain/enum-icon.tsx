import {
  Activity,
  Ban,
  Bot,
  CircleCheck,
  CircleHelp,
  CircleX,
  ClipboardCheck,
  Clock,
  Cpu,
  Crown,
  Equal,
  Eye,
  FilePen,
  FlaskConical,
  Gauge,
  GitCompareArrows,
  Globe,
  Layers,
  ListOrdered,
  Loader,
  Lock,
  Network,
  OctagonX,
  PencilLine,
  Plug,
  Rocket,
  Ruler,
  Scale,
  Sigma,
  Sparkles,
  Target,
  TrendingDown,
  TrendingUp,
  TriangleAlert,
  User,
  Wrench,
  type LucideIcon,
  type LucideProps,
} from "lucide-react";

import type { IconName } from "@/lib/enums";

/** Resolves enum icon names (see `IconName` in lib/enums) to lucide components. */
export const ENUM_ICONS: Record<IconName, LucideIcon> = {
  Activity,
  Ban,
  Bot,
  CircleCheck,
  CircleHelp,
  CircleX,
  ClipboardCheck,
  Clock,
  Cpu,
  Crown,
  Equal,
  Eye,
  FilePen,
  FlaskConical,
  Gauge,
  GitCompareArrows,
  Globe,
  Layers,
  ListOrdered,
  Loader,
  Lock,
  Network,
  OctagonX,
  PencilLine,
  Plug,
  Rocket,
  Ruler,
  Scale,
  Sigma,
  Sparkles,
  Target,
  TrendingDown,
  TrendingUp,
  TriangleAlert,
  User,
  Wrench,
};

export interface EnumIconProps extends LucideProps {
  name: IconName | undefined;
}

export function EnumIcon({ name, ...props }: EnumIconProps) {
  if (!name) return null;
  const Icon = ENUM_ICONS[name];
  return <Icon aria-hidden {...props} />;
}
