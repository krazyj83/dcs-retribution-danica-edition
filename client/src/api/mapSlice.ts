import { RootState } from "../app/store";
import { gameLoaded, gameUnloaded } from "./actions";
import { createSlice, PayloadAction } from "@reduxjs/toolkit";
import { LatLngLiteral } from "leaflet";

// The chosen base map and overlay check boxes are remembered between sessions
// (browser localStorage of the map's web profile).
const BASEMAP_STORAGE_KEY = "active_basemap_layer";
const OVERLAYS_STORAGE_KEY = "active_map_overlays";

const safeGetItem = (key: string): string | null => {
  try {
    return localStorage.getItem(key);
  } catch (error) {
    console.warn(`localStorage read failed for key "${key}":`, error);
    return null;
  }
};

const safeSetItem = (key: string, value: string): void => {
  try {
    localStorage.setItem(key, value);
  } catch (error) {
    console.warn(`localStorage write failed for key "${key}":`, error);
  }
};

const loadSavedOverlays = (): Record<string, boolean> => {
  const saved = safeGetItem(OVERLAYS_STORAGE_KEY);
  if (!saved) return {};
  try {
    return JSON.parse(saved);
  } catch (error) {
    console.warn("Failed to parse saved map overlays JSON:", error);
    return {};
  }
};

interface MapState {
  center: LatLngLiteral;
  // Persistent map type
  activeBaseMap: string | null;
  // Persistent map options
  overlayStates: Record<string, boolean>;
}

const initialState: MapState = {
  center: { lat: 0, lng: 0 },
  activeBaseMap: safeGetItem(BASEMAP_STORAGE_KEY),
  overlayStates: loadSavedOverlays(),
};

const mapSlice = createSlice({
  name: "map",
  initialState: initialState,
  reducers: {
    setActiveBaseMap(state, action: PayloadAction<string>) {
      state.activeBaseMap = action.payload;
      safeSetItem(BASEMAP_STORAGE_KEY, action.payload);
    },
    setOverlayState(
      state,
      action: PayloadAction<{ name: string; checked: boolean }>
    ) {
      const { name, checked } = action.payload;
      state.overlayStates[name] = checked;
      safeSetItem(OVERLAYS_STORAGE_KEY, JSON.stringify(state.overlayStates));
    },
  },
  extraReducers: (builder) => {
    builder.addCase(gameLoaded, (state, action) => {
      if (action.payload.map_center != null) {
        state.center = action.payload.map_center;
      }
    });
    builder.addCase(gameUnloaded, (state) => {
      state.center = { lat: 0, lng: 0 };
    });
  },
});

export const { setActiveBaseMap, setOverlayState } = mapSlice.actions;

export const selectMapCenter = (state: RootState) => state.map.center;
export const selectActiveBaseMap = (state: RootState) =>
  state.map.activeBaseMap;
export const selectOverlayChecked =
  (name: string, defaultChecked: boolean = false) =>
  (state: RootState): boolean =>
    state.map.overlayStates?.[name] ?? defaultChecked;

export default mapSlice.reducer;
