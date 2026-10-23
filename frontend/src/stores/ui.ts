import { create } from "zustand";

type UIState = { filter: string; setFilter: (filter: string) => void; infoOpen: boolean; setInfoOpen: (open: boolean) => void };
export const useUI = create<UIState>((set) => ({ filter: "All", setFilter: (filter) => set({ filter }), infoOpen: false, setInfoOpen: (infoOpen) => set({ infoOpen }) }));
