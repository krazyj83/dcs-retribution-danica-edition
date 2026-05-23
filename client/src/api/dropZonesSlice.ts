import { createAsyncThunk, createSlice, PayloadAction } from "@reduxjs/toolkit";
import { RootState } from "../app/store";
import { gameLoaded, gameUnloaded } from "./actions";

export interface DropZone {
  id: string;
  name: string;
  position: { lat: number; lng: number };
}

export function serverBase(): string {
  const params = new URLSearchParams(window.location.search);
  const server = params.get("server") ?? "localhost:16880";
  return `http://${server}`;
}

export const createDropZone = createAsyncThunk(
  "dropZones/create",
  async (args: { name: string; lat: number; lng: number }): Promise<DropZone> => {
    const res = await fetch(`${serverBase()}/drop-zones/`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(args),
    });
    if (!res.ok) throw new Error(`Create drop zone failed: ${res.status}`);
    return res.json();
  }
);

export const deleteDropZone = createAsyncThunk(
  "dropZones/delete",
  async (id: string): Promise<string> => {
    const res = await fetch(`${serverBase()}/drop-zones/${id}`, {
      method: "DELETE",
    });
    if (!res.ok) throw new Error(`Delete drop zone failed: ${res.status}`);
    return id;
  }
);

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
