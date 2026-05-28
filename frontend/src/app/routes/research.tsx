import { ResearchPage } from "@/features/research/research-page";
import { createRoute } from "@tanstack/react-router";
import { requireAuth } from "../auth-guards";
import { Route as rootRoute } from "./__root";

export type ResearchSearch = {
  project?: string;
  new?: string;
};

export const Route = createRoute({
  getParentRoute: () => rootRoute,
  path: "/research",
  beforeLoad: () => requireAuth(),
  validateSearch: (search: Record<string, unknown>): ResearchSearch => ({
    project: typeof search.project === "string" ? search.project : undefined,
    new: typeof search.new === "string" ? search.new : undefined,
  }),
  component: ResearchPage,
});
