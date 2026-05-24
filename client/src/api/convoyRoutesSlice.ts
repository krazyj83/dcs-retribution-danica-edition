import { createAsyncThunk, createSlice, PayloadAction } from "@reduxjs/toolkit";
import { RootState } from "../app/store";
import { gameLoaded, gameUnloaded } from "./actions";
import { serverBase } from "./dropZonesSlice";

export interface ConvoyRoute {
  id: string;
  name: string;
  start: { lat: number; lng: number };
  end: { lat: number; lng: number };
}

export const createConvoyRoute = createAsyncThunk(
  "convoyRoutes/create",
  async (args: {
    name: string;
    start_lat: number;
    start_lng: number;
    end_lat: number;
    end_lng: number;
  }): Promise<ConvoyRoute> => {
    const res = await fetch(`${serverBase()}/convoy-routes/`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(args),
    });
    if (!res.ok) throw new Error(`Create convoy route failed: ${res.status}`);
    return res.json();
  }
);

export const deleteConvoyRoute = createAsyncThunk(
  "convoyRoutes/delete",
  async (id: string): Promise<string> => {
    const res = await fetch(`${serverBase()}/convoy-routes/${id}`, {
      method: "DELETE",
    });
    if (!res.ok) throw new Error(`Delete convoy route failed: ${res.status}`);
    return id;
  }
);

interface ConvoyRoutesState {
  routes: ConvoyRoute[];
}

const initialState: ConvoyRoutesState = { routes: [] };

const convoyRoutesSlice = createSlice({
  name: "convoyRoutes",
  initialState,
  reducers: {},
  extraReducers: (builder) => {
    builder.addCase(gameLoaded, (state, action) => {
      if (action.payload?.convoy_routes) {
        state.routes = action.payload.convoy_routes;
      }
    });
    builder.addCase(gameUnloaded, (state) => {
      state.routes = [];
    });
    builder.addCase(createConvoyRoute.fulfilled, (state, action) => {
      state.routes.push(action.payload);
    });
    builder.addCase(deleteConvoyRoute.fulfilled, (state, action: PayloadAction<string>) => {
      state.routes = state.routes.filter((r) => r.id !== action.payload);
    });
  },
});

export const selectConvoyRoutes = (state: RootState) => state.convoyRoutes.routes;
export default convoyRoutesSlice.reducer;
