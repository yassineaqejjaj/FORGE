import {
  BarChart3,
  Bot,
  ClipboardCheck,
  Database,
  FlaskConical,
  Gavel,
  History,
  KeyRound,
  Layers,
  LayoutDashboard,
  Lightbulb,
  PencilRuler,
  Play,
  ScrollText,
  Settings,
  SlidersHorizontal,
  Users,
  Vault,
  type LucideIcon,
} from "lucide-react";

import type { Role } from "@/lib/enums";

/**
 * Navigation model — follows the user's mental model, not the internal structure:
 * Concevoir → Tester → Analyser → Améliorer (+ Configuration).
 *
 * Routes are unchanged (labels are translated, not URLs): /runs is « Exécutions », /benchmarks is
 * « Comparaisons ». Pages that belong to an object or an area (calibration, score configurations,
 * error analysis) are reached through local tabs, never added to the sidebar.
 */

/** Attention counters computed by `useNavBadges` (shown only when > 0). */
export type NavBadgeKey = "failedRuns" | "reviewQueue";

/** A page reached through local tabs of an entry (active state + breadcrumb only). */
export interface NavSubPage {
  href: string;
  label: string;
  icon: LucideIcon;
  description: string;
  keywords?: string[];
  minRole?: Role;
}

export interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
  description: string;
  /** Minimum role to show the entry (default: everyone). The API still enforces access. */
  minRole?: Role;
  /** Command palette keywords. */
  keywords?: string[];
  /** Singular noun used for dynamic breadcrumb leaves ("Exécution 3f2a9c1e"). */
  entity?: string;
  /** Attention counter shown next to the label. */
  badge?: NavBadgeKey;
  /** Other routes that belong to this entry (its local tabs). */
  subPages?: NavSubPage[];
  /** Shortcuts shown under the entry in the mobile menu and in the command palette. */
  children?: NavSubPage[];
}

export type NavSectionId = "overview" | "concevoir" | "tester" | "analyser" | "ameliorer" | "configuration";

export interface NavSection {
  id: NavSectionId;
  label: string;
  /** Category icon (mobile accordion). */
  icon: LucideIcon;
  /** One-line intent shown in the mobile menu. */
  hint: string;
  /** The overview is a single top-level destination without a group heading. */
  heading: boolean;
  items: NavItem[];
}

export const NAV_SECTIONS: NavSection[] = [
  {
    id: "overview",
    label: "Vue d'ensemble",
    icon: LayoutDashboard,
    hint: "Indicateurs, tendances et activité",
    heading: false,
    items: [
      {
        href: "/dashboard",
        label: "Vue d'ensemble",
        icon: LayoutDashboard,
        description: "Scores, tendances, régressions et activité récente",
        keywords: ["accueil", "dashboard", "tableau de bord", "kpi"],
      },
    ],
  },
  {
    id: "concevoir",
    label: "Concevoir",
    icon: PencilRuler,
    hint: "Définir ce qui doit être testé",
    heading: true,
    items: [
      {
        href: "/agents",
        label: "Agents",
        icon: Bot,
        description: "Agents évalués, versions immuables et comparaison de versions",
        keywords: ["versions", "prompts", "modèles", "outils", "diff", "système"],
        entity: "Agent",
      },
      {
        href: "/scenarios",
        label: "Scénarios",
        icon: ScrollText,
        description: "Bibliothèque de scénarios publics, privés et fresh, variantes",
        keywords: ["cas de test", "variantes", "privé", "fresh", "critères", "règles"],
        entity: "Scénario",
      },
      {
        href: "/datasets",
        label: "Datasets",
        icon: Database,
        description: "Documents de contexte des scénarios et jeux de référence (gold) pour la calibration",
        keywords: ["données", "documents", "contexte", "gold", "corpus"],
        entity: "Dataset",
      },
    ],
  },
  {
    id: "tester",
    label: "Tester",
    icon: Play,
    hint: "Exécuter les évaluations",
    heading: true,
    items: [
      {
        href: "/runs",
        label: "Exécutions",
        icon: Play,
        description: "Exécutions d'un agent sur un scénario : trace, scores expliqués, erreurs et feedback",
        keywords: ["runs", "traces", "timeline", "évaluations", "lancer"],
        entity: "Exécution",
        badge: "failedRuns",
        children: [
          { href: "/runs", label: "Toutes", icon: Play, description: "Toutes les exécutions" },
          {
            href: "/runs?status=pending&status=running&status=evaluating",
            label: "En cours",
            icon: Play,
            description: "Exécutions en attente, en cours ou en évaluation",
            keywords: ["running", "pending"],
          },
          {
            href: "/runs?status=completed&passed=true",
            label: "Réussies",
            icon: Play,
            description: "Exécutions évaluées au-dessus du seuil de réussite",
            keywords: ["passed", "succès"],
          },
          {
            href: "/runs?status=failed",
            label: "En erreur",
            icon: Play,
            description: "Exécutions en échec (erreur d'exécution, délai, budget)",
            keywords: ["failed", "échec", "erreurs"],
          },
        ],
      },
    ],
  },
  {
    id: "analyser",
    label: "Analyser",
    icon: BarChart3,
    hint: "Comprendre et comparer les résultats",
    heading: true,
    items: [
      {
        href: "/results",
        label: "Résultats",
        icon: BarChart3,
        description: "Scores par version d'agent sur la période et analyse des erreurs détectées",
        keywords: ["synthèse", "scores", "qualité", "erreurs", "hallucination", "taxonomie"],
        subPages: [
          {
            href: "/errors",
            label: "Erreurs détectées",
            icon: BarChart3,
            description: "Explorateur des erreurs par type, gravité, agent et scénario",
            keywords: ["erreurs", "taxonomie", "hallucination", "gravité"],
          },
        ],
      },
      {
        href: "/benchmarks",
        label: "Comparaisons",
        icon: Layers,
        description: "Matrices scénarios × versions d'agents, classements et robustesse",
        keywords: ["benchmarks", "classement", "matrice", "robustesse", "généralisation"],
        entity: "Comparaison",
      },
    ],
  },
  {
    id: "ameliorer",
    label: "Améliorer",
    icon: Lightbulb,
    hint: "Valider les nouvelles versions",
    heading: true,
    items: [
      {
        href: "/experiments",
        label: "Expériences",
        icon: FlaskConical,
        description: "Baseline vs candidate : verdicts, régressions et recommandation",
        keywords: ["a/b", "baseline", "candidate", "régressions", "ship", "garde-fou ci"],
        entity: "Expérience",
      },
      {
        href: "/reviews",
        label: "Revue humaine",
        icon: ClipboardCheck,
        description: "File de revue et évaluations humaines",
        keywords: ["humain", "annotation", "notation", "file"],
        minRole: "evaluator",
        badge: "reviewQueue",
      },
    ],
  },
  {
    id: "configuration",
    label: "Configuration",
    icon: Settings,
    hint: "Juges et administration",
    heading: true,
    items: [
      {
        href: "/judges",
        label: "Juges",
        icon: Gavel,
        description: "Juges LLM et heuristiques, configurations de score et calibration",
        keywords: ["llm", "judge", "prompts", "rubrique"],
        entity: "Juge",
        subPages: [
          {
            href: "/evaluation-configs",
            label: "Configurations de score",
            icon: SlidersHorizontal,
            description: "Pondérations, garde-fous, juges épinglés et agrégation",
            keywords: ["poids", "pondérations", "garde-fous", "gates", "score", "configurations"],
          },
          {
            href: "/calibration",
            label: "Calibration",
            icon: Gavel,
            description: "Accord IA / humain par juge et par critère",
            keywords: ["kappa", "accord", "spearman", "gold"],
          },
        ],
      },
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

/** Local tabs of the « Juges » area (Configuration). */
export const JUDGES_AREA_TABS: NavSubPage[] = [
  { href: "/judges", label: "Juges", icon: Gavel, description: "Juges LLM et heuristiques" },
  ...(NAV_SECTIONS.find((s) => s.id === "configuration")?.items[0]?.subPages ?? []),
];

/** Local tabs of the « Résultats » area (Analyser). */
export const RESULTS_AREA_TABS: NavSubPage[] = [
  { href: "/results", label: "Synthèse par version", icon: BarChart3, description: "Scores par version d'agent" },
  ...(NAV_SECTIONS.find((s) => s.id === "analyser")?.items[0]?.subPages ?? []),
];

export const ALL_NAV_ITEMS: NavItem[] = NAV_SECTIONS.flatMap((s) => s.items);

function matchesHref(pathname: string, href: string): boolean {
  const path = href.split("?")[0] ?? href;
  if (path === "/") return pathname === "/";
  return pathname === path || pathname.startsWith(`${path}/`);
}

export interface ActiveNav {
  section: NavSection;
  item: NavItem;
  /** Sub-page of the item when the route belongs to one of its local tabs. */
  subPage?: NavSubPage;
  /** Route prefix that matched (item href or sub-page href). */
  base: string;
}

/** Section + item (+ sub-page) matching the current pathname (longest match). */
export function activeNav(pathname: string): ActiveNav | undefined {
  let best: ActiveNav | undefined;
  for (const section of NAV_SECTIONS) {
    for (const item of section.items) {
      const candidates: { href: string; subPage?: NavSubPage }[] = [
        { href: item.href },
        ...(item.subPages ?? []).map((subPage) => ({ href: subPage.href, subPage })),
      ];
      for (const candidate of candidates) {
        if (matchesHref(pathname, candidate.href) && (!best || candidate.href.length > best.base.length)) {
          best = { section, item, subPage: candidate.subPage, base: candidate.href };
        }
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

/** Query keys that define the « view » of a list (Exécutions: status + result). */
const VIEW_KEYS = ["status", "passed"] as const;

/** True when the current URL shows exactly the view encoded in ``href`` (path + view keys). */
export function isViewActive(pathname: string, params: URLSearchParams, href: string): boolean {
  const [path, query] = href.split("?");
  if (pathname !== path) return false;
  const wanted = new URLSearchParams(query ?? "");
  return VIEW_KEYS.every((key) => {
    const a = [...wanted.getAll(key)].sort().join(",");
    const b = [...params.getAll(key)].sort().join(",");
    return a === b;
  });
}
