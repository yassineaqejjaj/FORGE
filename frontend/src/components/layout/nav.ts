import {
  Bot,
  Bug,
  ClipboardCheck,
  Crosshair,
  FlaskConical,
  Gavel,
  History,
  KeyRound,
  Layers,
  LayoutDashboard,
  Play,
  ScrollText,
  Settings,
  SlidersHorizontal,
  Users,
  Vault,
  type LucideIcon,
} from "lucide-react";

import type { Role } from "@/lib/enums";

export interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
  description: string;
  /** Minimum role to show the entry (default: everyone). The API still enforces access. */
  minRole?: Role;
  /** Command palette keywords. */
  keywords?: string[];
  /** Singular noun used for dynamic breadcrumb leaves ("Run 3f2a9c1e"). */
  entity?: string;
}

export interface NavSection {
  id: "pilotage" | "laboratoire" | "comparer" | "evaluer" | "administration";
  label: string;
  items: NavItem[];
}

export const NAV_SECTIONS: NavSection[] = [
  {
    id: "pilotage",
    label: "Pilotage",
    items: [
      {
        href: "/",
        label: "Tableau de bord",
        icon: LayoutDashboard,
        description: "Scores, tendances, régressions et activité récente",
        keywords: ["accueil", "dashboard", "kpi", "vue d'ensemble"],
      },
    ],
  },
  {
    id: "laboratoire",
    label: "Laboratoire",
    items: [
      {
        href: "/agents",
        label: "Agents",
        icon: Bot,
        description: "Agents évalués, versions immuables et comparaison de versions",
        keywords: ["versions", "prompts", "modèles", "outils", "diff"],
        entity: "Agent",
      },
      {
        href: "/scenarios",
        label: "Scénarios",
        icon: ScrollText,
        description: "Bibliothèque de scénarios publics, privés et fresh, variantes",
        keywords: ["cas de test", "dataset", "variantes", "privé", "fresh"],
        entity: "Scénario",
      },
      {
        href: "/runs",
        label: "Runs",
        icon: Play,
        description: "Exécutions, traces, scores, erreurs et feedback",
        keywords: ["exécutions", "traces", "timeline", "évaluations"],
        entity: "Run",
      },
    ],
  },
  {
    id: "comparer",
    label: "Comparer",
    items: [
      {
        href: "/benchmarks",
        label: "Benchmarks",
        icon: Layers,
        description: "Matrices scénarios × versions d'agents, classements et robustesse",
        keywords: ["classement", "matrice", "robustesse", "généralisation"],
        entity: "Benchmark",
      },
      {
        href: "/experiments",
        label: "Expériences",
        icon: FlaskConical,
        description: "Baseline vs candidate : verdicts, régressions et recommandation",
        keywords: ["a/b", "baseline", "candidate", "régressions", "ship"],
        entity: "Expérience",
      },
    ],
  },
  {
    id: "evaluer",
    label: "Évaluer",
    items: [
      {
        href: "/judges",
        label: "Juges",
        icon: Gavel,
        description: "Juges LLM et heuristiques, versions et tests",
        keywords: ["llm", "judge", "prompts", "rubrique"],
        entity: "Juge",
      },
      {
        href: "/evaluation-configs",
        label: "Configurations",
        icon: SlidersHorizontal,
        description: "Pondérations, garde-fous, juges épinglés et agrégation",
        keywords: ["poids", "pondérations", "garde-fous", "gates", "score"],
        entity: "Configuration",
      },
      {
        href: "/reviews",
        label: "Revue humaine",
        icon: ClipboardCheck,
        description: "File de revue et évaluations humaines",
        keywords: ["humain", "annotation", "notation", "file"],
      },
      {
        href: "/calibration",
        label: "Calibration",
        icon: Crosshair,
        description: "Accord IA / humain par juge et par critère",
        keywords: ["kappa", "accord", "spearman", "gold"],
      },
      {
        href: "/errors",
        label: "Erreurs",
        icon: Bug,
        description: "Explorateur des erreurs détectées par type, gravité et agent",
        keywords: ["taxonomie", "hallucination", "gravité"],
      },
    ],
  },
  {
    id: "administration",
    label: "Administration",
    items: [
      {
        href: "/settings",
        label: "Paramètres",
        icon: Settings,
        description: "Utilisateurs, clés d'API, identifiants fournisseurs et audit",
        minRole: "maintainer",
        keywords: ["utilisateurs", "clés", "api", "identifiants", "audit", "administration"],
      },
    ],
  },
];

/** Settings sub-navigation (tabs of /settings). */
export const SETTINGS_NAV: NavItem[] = [
  {
    href: "/settings/users",
    label: "Utilisateurs",
    icon: Users,
    description: "Comptes, rôles et habilitations",
    minRole: "admin",
    keywords: ["comptes", "rôles", "habilitation"],
  },
  {
    href: "/settings/api-keys",
    label: "Clés d'API",
    icon: KeyRound,
    description: "Clés pour la CI et pour les traces poussées par les agents",
    minRole: "admin",
    keywords: ["token", "ci", "traces:write"],
  },
  {
    href: "/settings/credentials",
    label: "Identifiants",
    icon: Vault,
    description: "Identifiants fournisseurs chiffrés (LLM, NOVA, ORBIT, HTTP)",
    minRole: "admin",
    keywords: ["secrets", "fournisseurs", "clés llm", "rotation"],
  },
  {
    href: "/settings/audit",
    label: "Audit",
    icon: History,
    description: "Journal de toutes les mutations",
    minRole: "maintainer",
    keywords: ["journal", "historique", "traçabilité"],
  },
];

export const ALL_NAV_ITEMS: NavItem[] = NAV_SECTIONS.flatMap((s) => s.items);

function matchesHref(pathname: string, href: string): boolean {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(`${href}/`);
}

/** Section + item matching the current pathname (longest match). */
export function activeNav(pathname: string): { section: NavSection; item: NavItem } | undefined {
  let best: { section: NavSection; item: NavItem } | undefined;
  for (const section of NAV_SECTIONS) {
    for (const item of section.items) {
      if (matchesHref(pathname, item.href) && (!best || item.href.length > best.item.href.length)) {
        best = { section, item };
      }
    }
  }
  return best;
}

export function activeSettingsNav(pathname: string): NavItem | undefined {
  return SETTINGS_NAV.find((item) => matchesHref(pathname, item.href));
}

export function isActiveHref(pathname: string, href: string): boolean {
  return matchesHref(pathname, href);
}
