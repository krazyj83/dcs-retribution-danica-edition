/**
 * dropZonesSlice.ts
 *
 * Redux state for player-placed campaign drop zones.
 *
 * Initial data: included in the GameJs payload via the Python GameJs.from_game()
 * call (added by the patch script).
 *
 * Mutations:
 *   createDropZone  – POST /drop-zones/  → adds marker to map
 *   deleteDropZone  – DELETE /drop-zones/{id}  → removes marker
 *
 * "Create Mission" is NOT a Redux action — it's a fire-and-forget POST to
 * /qt/create-package/drop-zone/{id} which opens the Retribution package
 * dialog on the Python side. No state change needed in Redux for that.
 */

import { createAsyncThunk, createSlice, PayloadAction } from "@reduxjs/toolkit";
import { RootState } from "../app/store";
import { gameLoaded, gameUnloaded } from "./actions";

// ── Types ────────────────────────────────────────────────────────────────────

export interface DropZone {
  id: string;
  name: string;
  position: { lat: number; lng: number };
}

// ── Server URL helper ─────────────────────────────────────────────────────────
// Reads the ?server=host:port query param that QLiberationMap.py injects.

export function serverBase(): string {
  const params = new URLSearchParams(window.location.search);
  const server = params.get("server") ?? "localhost:16880";
  return `http://${server}`;
}

// ── Async thunks ──────────────────────────────────────────────────────────────

export const createDropZone = createAsyncThunk<
  DropZone,
  { name: string; lat: number; lng: number }
>("dropZones/create", async (args) => {
  const res = await fetch(`${serverBase()}/drop-zones/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(args),
  });
  if (!res.ok) throw new Error(`Create drop zone failed: ${res.status}`);
  return res.json() as Promise<DropZone>;
});

export const deleteDropZone = createAsyncThunk<string, string>(
  "dropZones/delete",
  async (id) => {
    const res = await fetch(`${serverBase()}/drop-zones/${id}`, {
      method: "DELETE",
    });
    if (!res.ok) throw new Error(`Delete drop zone failed: ${res.status}`);
    return id;
  }
);

// ── Slice ─────────────────────────────────────────────────────────────────────

interface DropZonesState {
  zones: DropZone[];
}

const initialState: DropZonesState = { zones: [] };

const dropZonesSlice = createSlice({
  name: "dropZones",
  initialState,
  reducers: {},
  extraReducers: (builder) => {
    builder.addCase(gameLoaded, (state, action) => {
      // Hydrate from Python GameJs payload
      if (action.payload?.drop_zones) {
        state.zones = action.payload.drop_zones;
      }
    });
    builder.addCase(gameUnloaded, (state) => {
      state.zones = [];
    });
    builder.addCase(createDropZone.fulfilled, (state, action) => {
      state.zones.push(action.payload);
    });
    builder.addCase(deleteDropZone.fulfilled, (state, action: PayloadAction<string>) => {
      state.zones = state.zones.filter((z) => z.id !== action.payload);
    });
  },
});

export const selectDropZones = (state: RootState) => state.dropZones.zones;
export default dropZonesSlice.reducer;
