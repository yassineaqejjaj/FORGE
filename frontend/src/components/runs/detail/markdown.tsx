"use client";

import * as React from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

import { cn } from "@/lib/utils";

const components: Components = {
  h1: ({ node: _n, ...p }) => <h2 className="mb-2 mt-5 text-lg font-semibold tracking-tight first:mt-0" {...p} />,
  h2: ({ node: _n, ...p }) => <h3 className="mb-2 mt-5 text-[15px] font-semibold tracking-tight first:mt-0" {...p} />,
  h3: ({ node: _n, ...p }) => <h4 className="mb-1.5 mt-4 text-sm font-semibold first:mt-0" {...p} />,
  h4: ({ node: _n, ...p }) => <h5 className="mb-1 mt-3 text-[13px] font-semibold first:mt-0" {...p} />,
  p: ({ node: _n, ...p }) => <p className="my-2 leading-relaxed" {...p} />,
  ul: ({ node: _n, ...p }) => <ul className="my-2 list-disc space-y-1 pl-5 marker:text-subtle-foreground" {...p} />,
  ol: ({ node: _n, ...p }) => <ol className="my-2 list-decimal space-y-1 pl-5 marker:text-subtle-foreground" {...p} />,
  li: ({ node: _n, ...p }) => <li className="leading-relaxed" {...p} />,
  a: ({ node: _n, ...p }) => <a className="text-primary underline underline-offset-2" target="_blank" rel="noopener noreferrer" {...p} />,
  blockquote: ({ node: _n, ...p }) => <blockquote className="my-2 border-l-2 border-border-strong pl-3 text-muted-foreground" {...p} />,
  code: ({ node: _n, className, ...p }) => (
    <code className={cn("rounded bg-muted px-1 py-0.5 font-mono text-[12px]", className)} {...p} />
  ),
  pre: ({ node: _n, ...p }) => (
    <pre className="my-2 overflow-x-auto rounded-lg border border-border bg-muted/50 p-3 font-mono text-[12px] [&_code]:bg-transparent [&_code]:p-0" {...p} />
  ),
  table: ({ node: _n, ...p }) => (
    <div className="my-2 overflow-x-auto">
      <table className="w-full border-collapse text-[12.5px]" {...p} />
    </div>
  ),
  th: ({ node: _n, ...p }) => <th className="border border-border bg-muted/60 px-2 py-1 text-left font-semibold" {...p} />,
  td: ({ node: _n, ...p }) => <td className="border border-border px-2 py-1 align-top" {...p} />,
  hr: () => <hr className="my-4 border-border" />,
};

/** Agent output rendered as Markdown (GFM). Raw HTML is never rendered. */
export function Markdown({ children, className }: { children: string; className?: string }) {
  return (
    <div className={cn("min-w-0 break-words text-[13.5px] text-foreground", className)}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {children}
      </ReactMarkdown>
    </div>
  );
}
