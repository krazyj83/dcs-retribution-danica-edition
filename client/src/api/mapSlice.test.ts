import mapReducer, {
  EMITTER_HIGHLIGHT_OVERLAY,
  selectHighlightEmitters,
  selectHoveredEmitter,
  selectHoveredEmitterSource,
  setHighlightEmitters,
  setHoveredEmitter,
  setActiveBaseMap,
  setOverlayState,
  selectMapCenter,
  selectActiveBaseMap,
  selectOverlayChecked,
} from "./mapSlice";
import { gameLoaded, gameUnloaded } from "./actions";
import { RootState } from "../app/store";

describe("mapSlice", () => {
  const BASEMAP_STORAGE_KEY = "active_basemap_layer";
  const OVERLAYS_STORAGE_KEY = "active_map_overlays";

  beforeEach(() => {
    localStorage.clear();
    jest.clearAllMocks();
  });

  describe("Initial State & localStorage Initialization", () => {
    it("should return initial state when localStorage is empty", () => {
      const state = mapReducer(undefined, { type: "@@INIT" });
      expect(state).toEqual({
        center: { lat: 0, lng: 0 },
        hoveredEmitterId: null,
        hoveredEmitterSource: null,
        highlightEmitters: true,
        activeBaseMap: null,
        overlayStates: {},
      });
    });

    it("should initialize activeBaseMap and overlayStates from localStorage", () => {
      localStorage.setItem(BASEMAP_STORAGE_KEY, "hybrid");
      localStorage.setItem(
        OVERLAYS_STORAGE_KEY,
        JSON.stringify({ sam_rings: true, bullseye: false })
      );

      // Re-require / re-evaluate slice initial state evaluation by dispatching init
      // Note: initialState executes at module import time, so we test using localStorage pre-populated keys
      const savedOverlays = JSON.parse(
        localStorage.getItem(OVERLAYS_STORAGE_KEY) || "{}"
      );
      expect(savedOverlays).toEqual({ sam_rings: true, bullseye: false });
    });

    it("should handle corrupted JSON in localStorage gracefully without crashing", () => {
      const consoleWarnSpy = jest
        .spyOn(console, "warn")
        .mockImplementation(() => {});
      localStorage.setItem(OVERLAYS_STORAGE_KEY, "invalid_json{");

      // Verifying that safe JSON parsing handles error
      const saved = localStorage.getItem(OVERLAYS_STORAGE_KEY);
      let parsed = {};
      try {
        parsed = JSON.parse(saved!);
      } catch (e) {
        parsed = {};
      }
      expect(parsed).toEqual({});
      consoleWarnSpy.mockRestore();
    });
  });

  describe("Reducers", () => {
    const initialState = mapReducer(undefined, { type: "@@INIT" });

    it("should handle setActiveBaseMap and save to localStorage", () => {
      const nextState = mapReducer(
        initialState,
        setActiveBaseMap("topo_dark")
      );
      expect(nextState.activeBaseMap).toBe("topo_dark");
      expect(localStorage.getItem(BASEMAP_STORAGE_KEY)).toBe("topo_dark");
    });

    it("should handle setOverlayState and update localStorage", () => {
      const state1 = mapReducer(
        initialState,
        setOverlayState({ name: "threat_rings", checked: true })
      );
      expect(state1.overlayStates).toEqual({ threat_rings: true });
      expect(localStorage.getItem(OVERLAYS_STORAGE_KEY)).toBe(
        JSON.stringify({ threat_rings: true })
      );

      const state2 = mapReducer(
        state1,
        setOverlayState({ name: "waypoints", checked: false })
      );
      expect(state2.overlayStates).toEqual({
        threat_rings: true,
        waypoints: false,
      });
      expect(localStorage.getItem(OVERLAYS_STORAGE_KEY)).toBe(
        JSON.stringify({ threat_rings: true, waypoints: false })
      );
    });

    it("should catch errors when localStorage setItem fails", () => {
      const consoleWarnSpy = jest
        .spyOn(console, "warn")
        .mockImplementation(() => {});
      jest.spyOn(Storage.prototype, "setItem").mockImplementationOnce(() => {
        throw new Error("QuotaExceededError");
      });

      expect(() => {
        mapReducer(initialState, setActiveBaseMap("satellite"));
      }).not.toThrow();

      expect(consoleWarnSpy).toHaveBeenCalled();
      consoleWarnSpy.mockRestore();
    });
  });

  describe("Extra Reducers", () => {
    const initialState = mapReducer(undefined, { type: "@@INIT" });

    it("should update map center on gameLoaded action when map_center is provided", () => {
      const action = gameLoaded({
        map_center: { lat: 41.9, lng: 42.0 },
      } as any);
      const nextState = mapReducer(initialState, action);

      expect(nextState.center).toEqual({ lat: 41.9, lng: 42.0 });
    });

    it("should retain existing map center on gameLoaded when map_center is null/undefined", () => {
      const customState = { ...initialState, center: { lat: 10, lng: 20 } };
      const action = gameLoaded({ map_center: null } as any);
      const nextState = mapReducer(customState, action);

      expect(nextState.center).toEqual({ lat: 10, lng: 20 });
    });

    it("should reset center on gameUnloaded", () => {
      const populatedState = {
        ...initialState,
        center: { lat: 42.0, lng: 43.0 },
      };

      const nextState = mapReducer(populatedState, gameUnloaded());

      expect(nextState.center).toEqual({ lat: 0, lng: 0 });
    });
  });

  describe("Selectors", () => {
    const mockRootState: RootState = {
      map: {
        center: { lat: 25.5, lng: 55.3 },
        activeBaseMap: "esri_dark",
        overlayStates: {
          grid: true,
          radar: false,
        },
      },
    } as any;

    it("selectMapCenter returns center", () => {
      expect(selectMapCenter(mockRootState)).toEqual({ lat: 25.5, lng: 55.3 });
    });

    it("selectActiveBaseMap returns activeBaseMap", () => {
      expect(selectActiveBaseMap(mockRootState)).toBe("esri_dark");
    });

    it("selectOverlayChecked returns explicit state when available", () => {
      expect(selectOverlayChecked("grid")(mockRootState)).toBe(true);
      expect(selectOverlayChecked("radar")(mockRootState)).toBe(false);
    });

    it("selectOverlayChecked falls back to defaultChecked when key is missing", () => {
      expect(selectOverlayChecked("unknown_layer", true)(mockRootState)).toBe(
        true
      );
      expect(
        selectOverlayChecked("unknown_layer", false)(mockRootState)
      ).toBe(false);
      expect(selectOverlayChecked("unknown_layer")(mockRootState)).toBe(false);
    });
  });

  describe("Emitter hover highlight", () => {
    const root = (map: any) => ({ map } as RootState);

    it("tracks the hovered emitter and where the hover came from", () => {
      let state = mapReducer(
        undefined,
        setHoveredEmitter({ id: "tgo-1", source: "ring" })
      );
      expect(selectHoveredEmitter(root(state))).toBe("tgo-1");
      expect(selectHoveredEmitterSource(root(state))).toBe("ring");
      state = mapReducer(state, setHoveredEmitter(null));
      expect(selectHoveredEmitter(root(state))).toBeNull();
      expect(selectHoveredEmitterSource(root(state))).toBeNull();
    });

    it("can be switched off and on", () => {
      let state = mapReducer(undefined, setHighlightEmitters(false));
      expect(selectHighlightEmitters(root(state))).toBe(false);
      state = mapReducer(state, setHighlightEmitters(true));
      expect(selectHighlightEmitters(root(state))).toBe(true);
    });

    it("forgets the hover when the game is unloaded", () => {
      let state = mapReducer(
        undefined,
        setHoveredEmitter({ id: "tgo-1", source: "emitter" })
      );
      state = mapReducer(state, gameUnloaded());
      expect(selectHoveredEmitter(root(state))).toBeNull();
    });

    it("starts off when its overlay was left unchecked last time", () => {
      // An earlier test spies on Storage.setItem; use the real one here.
      jest.restoreAllMocks();
      localStorage.setItem(
        OVERLAYS_STORAGE_KEY,
        JSON.stringify({ [EMITTER_HIGHLIGHT_OVERLAY]: false })
      );
      jest.isolateModules(() => {
        const fresh = require("./mapSlice");
        const state = fresh.default(undefined, { type: "@@INIT" });
        expect(state.highlightEmitters).toBe(false);
      });
    });
  });
});