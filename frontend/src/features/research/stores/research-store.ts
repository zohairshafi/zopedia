import { create } from "zustand";
import type {
  ResearchConfig,
  ResearchPhase,
  ResearchState,
  SourceSuggestion,
  RoundResult,
  ToolActivity,
} from "../types";
import { defaultResearchConfig } from "../types";

interface ResearchActions {
  setConfig: (config: ResearchConfig) => void;
  setPhase: (phase: ResearchPhase) => void;
  setCurrentRound: (round: number) => void;
  setTotalRounds: (total: number) => void;
  setSources: (sources: SourceSuggestion[]) => void;
  addRoundResult: (result: RoundResult) => void;
  appendFinalReport: (chunk: string) => void;
  setError: (error: string | null) => void;
  setSurveyContent: (content: string) => void;
  setMaintenanceStep: (step: string, details: unknown) => void;
  setTotalIngested: (count: number) => void;
  setWarnings: (warnings: { url: string; error: string }[]) => void;
  setSessionId: (id: string | null) => void;
  setToolStatus: (status: string) => void;
  addToolActivity: (activity: ToolActivity) => void;
  completeToolActivity: (toolCallId: string, sizeChars: number, preview: string) => void;
  clearToolActivities: () => void;
  setResearchTitle: (title: string) => void;
  reset: () => void;
}

const initialState: ResearchState = {
  config: null,
  sessionId: null,
  phase: "idle",
  currentRound: 0,
  totalRounds: 0,
  sources: [],
  roundResults: [],
  finalReport: "",
  error: null,
  surveyContent: "",
  maintenanceSteps: {},
  totalIngested: 0,
  warnings: [],
  toolStatus: "",
  toolActivities: [],
  researchTitle: "",
};

export const useResearchStore = create<ResearchState & ResearchActions>((set) => ({
  ...initialState,

  setConfig: (config) => set({ config }),
  setPhase: (phase) => set({ phase }),
  setCurrentRound: (round) => set({ currentRound: round }),
  setTotalRounds: (total) => set({ totalRounds: total }),
  setSources: (sources) => set({ sources }),
  addRoundResult: (result) =>
    set((s) => ({ roundResults: [...s.roundResults, result] })),
  appendFinalReport: (chunk) =>
    set((s) => ({ finalReport: s.finalReport + chunk })),
  setError: (error) => set({ error, phase: error ? "error" : undefined }),
  setSurveyContent: (content) => set({ surveyContent: content }),
  setMaintenanceStep: (step, details) =>
    set((s) => ({
      maintenanceSteps: { ...s.maintenanceSteps, [step]: details },
    })),
  setTotalIngested: (count) => set({ totalIngested: count }),
  setWarnings: (warnings) => set({ warnings }),
  setSessionId: (id) => set({ sessionId: id }),
  setToolStatus: (status) => set({ toolStatus: status }),
  addToolActivity: (activity) =>
    set((s) => ({ toolActivities: [...s.toolActivities, activity] })),
  completeToolActivity: (toolCallId: string, sizeChars: number, preview: string) =>
    set((s) => ({
      toolActivities: s.toolActivities.map((a) =>
        a.toolCallId === toolCallId ? { ...a, sizeChars, preview } : a
      ),
    })),
  clearToolActivities: () => set({ toolActivities: [], toolStatus: "" }),
  setResearchTitle: (title) => set({ researchTitle: title }),
  reset: () =>
    set({
      ...initialState,
      config: null,
    }),
}));
