import { Bot, ClipboardCheck, FlaskConical, Layers, LayoutDashboard, PencilRuler, Play, ScrollText, Users, type LucideIcon } from "lucide-react";

import { hasMinRole, type Role } from "@/lib/enums";

/** The four moments of the FORGE loop, in the order of the sidebar. */
export interface JourneyStage {
  id: "concevoir" | "tester" | "analyser" | "ameliorer";
  label: string;
  icon: LucideIcon;
  text: string;
}

export const JOURNEY: JourneyStage[] = [
  {
    id: "concevoir",
    label: "Concevoir",
    icon: PencilRuler,
    text: "Enregistrez vos agents (versions immuables) et décrivez ce qui doit être testé : scénarios, critères, règles.",
  },
  {
    id: "tester",
    label: "Tester",
    icon: Play,
    text: "Lancez des exécutions : FORGE fait tourner l'agent sur un scénario et garde la trace complète de ce qu'il a fait.",
  },
  {
    id: "analyser",
    label: "Analyser",
    icon: Layers,
    text: "Lisez des scores explicables, comparez agents et versions, repérez les types d'erreurs et leur gravité.",
  },
  {
    id: "ameliorer",
    label: "Améliorer",
    icon: FlaskConical,
    text: "Comparez une version candidate à sa référence : régressions par scénario, niveau de confiance, recommandation.",
  },
];

/** What each role can do, as a standalone sentence (the platform's role descriptions are cumulative). */
export const ROLE_SUMMARY: Record<Role, string> = {
  viewer: "Vous pouvez tout consulter : agents, scénarios, exécutions, scores et comparaisons.",
  evaluator: "Vous pouvez tout consulter et apporter des évaluations humaines sur les résultats.",
  editor: "Vous pouvez créer et lancer : agents et versions, scénarios, exécutions, comparaisons et expériences.",
  maintainer: "Vous gérez aussi les scénarios privés, les juges, les configurations de score et la taxonomie d'erreurs.",
  admin: "Vous avez tous les droits, y compris la gestion des utilisateurs, des clés d'API et des identifiants fournisseurs.",
};

export interface FirstAction {
  href: string;
  label: string;
  text: string;
  icon: LucideIcon;
}

/** Suggested first steps. They follow what the role can actually do (the API still enforces access). */
export function firstActions(role: Role | null | undefined): FirstAction[] {
  const actions: FirstAction[] = [
    {
      href: "/dashboard",
      label: "Parcourir la vue d'ensemble",
      text: "Scores, tendances et ce qui demande votre attention.",
      icon: LayoutDashboard,
    },
  ];
  if (hasMinRole(role, "editor")) {
    actions.push(
      {
        href: "/agents",
        label: "Consulter ou ajouter un agent",
        text: "Les agents de démonstration permettent d'essayer FORGE sans clé LLM.",
        icon: Bot,
      },
      {
        href: "/scenarios",
        label: "Parcourir les scénarios",
        text: "Publics, privés ou « fresh » : la matière première de toute évaluation.",
        icon: ScrollText,
      },
      {
        href: "/runs?new=1",
        label: "Lancer une première exécution",
        text: "Un scénario, un agent, et vous obtenez trace, scores et feedback.",
        icon: Play,
      },
    );
  } else {
    actions.push({
      href: "/runs",
      label: "Explorer les exécutions",
      text: "Ouvrez un run pour lire la trace, les scores et leurs justifications.",
      icon: Play,
    });
    if (hasMinRole(role, "evaluator")) {
      actions.push({
        href: "/reviews",
        label: "Passer en revue des résultats",
        text: "Votre évaluation humaine calibre les juges automatiques.",
        icon: ClipboardCheck,
      });
    }
  }
  if (hasMinRole(role, "admin")) {
    actions.push({
      href: "/settings/users",
      label: "Inviter votre équipe",
      text: "Créez les comptes et choisissez rôle et habilitation de chacun.",
      icon: Users,
    });
  }
  return actions;
}
