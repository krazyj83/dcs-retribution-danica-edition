import { createAsyncThunk, createSlice } from "@reduxjs/toolkit";
import { RootState } from "../app/store";
import { gameLoaded, gameUnloaded } from "./actions";
import { serverBase } from "./dropZonesSlice";

// Fuel and ammunition of one friendly base (game/logistics/supply_status.py).
export interface BaseSupply {
  id: string;
  name: string;
  position: { lat: number; lng: number };
  fuel: number;
  fuel_capacity: number;
  ammunition: number;
  ammunition_capacity: number;
  supplies: number;
  supplies_capacity: number;
  fuel_turns_left?: number | null;
  unlimited_fuel: boolean;
  status: "ok" | "low" | "critical" | string;
  reasons: string[];
  // "red": an enemy base known from recon (game/logistics/intel.py); its
  // amounts are percentages and intel_age is the report's age in turns.
  side?: string;
  intel_age?: number | null;
}

// Stock changes mid-turn too (Logistics window, supply flights), so the
// layer refreshes this now and then on top of every game (re)load.
export const fetchSupplyStatus = createAsyncThunk(
  "supplyStatus/fetch",
  async (): Promise<BaseSupply[]> => {
    const res = await fetch(`${serverBase()}/logistics/supply-status`);
    if (!res.ok) throw new Error(`Supply status failed: ${res.status}`);
    return res.json();
  }
);

interface SupplyStatusState {
  bases: BaseSupply[];
}

const initialState: SupplyStatusState = { bases: [] };

const supplyStatusSlice = createSlice({
  name: "supplyStatus",
  initialState,
  reducers: {},
  extraReducers: (builder) => {
    builder.addCase(gameLoaded, (state, action) => {
      const payload = action.payload as { supply_status?: BaseSupply[] };
      if (payload?.supply_status) {
        state.bases = payload.supply_status;
      }
    });
    builder.addCase(gameUnloaded, (state) => {
      state.bases = [];
    });
    builder.addCase(fetchSupplyStatus.fulfilled, (state, action) => {
      state.bases = action.payload;
    });
  },
});

const NO_BASES: BaseSupply[] = [];
export const selectSupplyStatus = (state: RootState) =>
  state.supplyStatus?.bases ?? NO_BASES;
export default supplyStatusSlice.reducer;
