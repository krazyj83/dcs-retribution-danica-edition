import { renderWithProviders } from "../../testutils";
import DropZoneLayer, {
  DROP_ZONE_OVERLAY,
  MapRightClickHandler,
} from "./DropZoneLayer";
import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { PropsWithChildren } from "react";

// Map event handlers registered by the layer through useMapEvents.
let mapHandlers: Record<string, (e: any) => void> = {};

jest.mock("react-leaflet", () => ({
  useMapEvents: (handlers: Record<string, (e: any) => void>) => {
    mapHandlers = handlers;
  },
  LayerGroup: (props: PropsWithChildren<any>) => <div>{props.children}</div>,
  Popup: (props: PropsWithChildren<any>) => <div>{props.children}</div>,
  Marker: (props: PropsWithChildren<any>) => <div>{props.children}</div>,
  Tooltip: (props: PropsWithChildren<any>) => <span>{props.children}</span>,
  CircleMarker: (props: PropsWithChildren<any>) => <div>{props.children}</div>,
  Polyline: (props: PropsWithChildren<any>) => <div>{props.children}</div>,
}));

const rightClick = (lat: number, lng: number) =>
  act(() => {
    mapHandlers.contextmenu({
      originalEvent: { preventDefault: () => {} },
      latlng: { lat, lng },
    });
  });

// The map as LiberationMap builds it: the saved zones and routes in their
// overlay, the right-click handler on the map itself.
const MapLayers = () => (
  <>
    <DropZoneLayer />
    <MapRightClickHandler />
  </>
);

const mockFetch = (status: number, body: unknown) => {
  const fetchMock = jest.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
  });
  global.fetch = fetchMock as any;
  return fetchMock;
};

describe("DropZoneLayer right-click workflow", () => {
  beforeEach(() => {
    mapHandlers = {};
    jest.spyOn(window, "prompt").mockImplementation(() => {
      throw new Error("window.prompt must not be used");
    });
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  it("creates a drop zone from the in-map name form", async () => {
    const fetchMock = mockFetch(201, {
      id: "dz-1",
      name: "DZ Alpha",
      position: { lat: 42.1, lng: 41.7 },
    });
    const { store } = renderWithProviders(<MapLayers />);

    rightClick(42.1, 41.7);
    fireEvent.click(screen.getByText(/Add Drop Zone/));
    fireEvent.change(screen.getByLabelText("Name"), {
      target: { value: "DZ Alpha" },
    });
    fireEvent.click(screen.getByText(/Save/));

    await waitFor(() =>
      expect(store.getState().dropZones.zones).toHaveLength(1)
    );
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toMatch(/\/drop-zones\/$/);
    expect(JSON.parse(init.body)).toEqual({
      name: "DZ Alpha",
      lat: 42.1,
      lng: 41.7,
    });
    // Form closed, the marker for the new zone is shown.
    await waitFor(() => expect(screen.queryByLabelText("Name")).toBeNull());
    expect(screen.getByText("🎯 DZ Alpha")).toBeInTheDocument();
  });

  it("keeps the form open and shows the error when the server refuses", async () => {
    jest.spyOn(console, "error").mockImplementation(() => {});
    mockFetch(503, {});
    const { store } = renderWithProviders(<MapLayers />);

    rightClick(1, 2);
    fireEvent.click(screen.getByText(/Add Drop Zone/));
    fireEvent.click(screen.getByText(/Save/));

    expect(await screen.findByText(/Could not save/)).toBeInTheDocument();
    expect(screen.getByLabelText("Name")).toBeInTheDocument();
    expect(store.getState().dropZones.zones).toHaveLength(0);
  });

  it("creates a convoy route from two right-clicks and a name", async () => {
    const fetchMock = mockFetch(201, {
      id: "r-1",
      name: "MSR Tampa",
      start: { lat: 1, lng: 2 },
      end: { lat: 3, lng: 4 },
    });
    const { store } = renderWithProviders(<MapLayers />);

    rightClick(1, 2);
    fireEvent.click(screen.getByText(/Add Convoy Route/));
    expect(screen.getByText(/right-click to set end point/)).toBeInTheDocument();

    // Moving the mouse draws a live line with the drive time.
    act(() => {
      mapHandlers.mousemove({ latlng: { lat: 3, lng: 4 } });
    });
    expect(screen.getByText(/by road at 40 km\/h/)).toBeInTheDocument();

    rightClick(3, 4);
    // The name form shows the same estimate.
    expect(screen.getByText(/by road at 40 km\/h/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Name"), {
      target: { value: "MSR Tampa" },
    });
    fireEvent.click(screen.getByText(/Save/));

    await waitFor(() =>
      expect(store.getState().convoyRoutes.routes).toHaveLength(1)
    );
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toMatch(/\/convoy-routes\/$/);
    expect(JSON.parse(init.body)).toEqual({
      name: "MSR Tampa",
      start_lat: 1,
      start_lng: 2,
      end_lat: 3,
      end_lng: 4,
      repeat: false,
    });
  });

  it("creates a standing route and can stop it repeating", async () => {
    const created = {
      id: "r-2",
      name: "MSR Denver",
      start: { lat: 1, lng: 2 },
      end: { lat: 3, lng: 4 },
      repeat: true,
    };
    const fetchMock = mockFetch(201, created);
    const { store } = renderWithProviders(<MapLayers />);

    rightClick(1, 2);
    fireEvent.click(screen.getByText(/Add Convoy Route/));
    rightClick(3, 4);
    fireEvent.click(screen.getByLabelText(/Repeat every turn/));
    fireEvent.click(screen.getByText(/Save/));

    await waitFor(() =>
      expect(store.getState().convoyRoutes.routes).toHaveLength(1)
    );
    expect(JSON.parse(fetchMock.mock.calls[0][1].body).repeat).toBe(true);
    expect(screen.getByText(/Standing route/)).toBeInTheDocument();

    const patchMock = mockFetch(200, { ...created, repeat: false });
    fireEvent.click(screen.getByText(/Stop repeating/));
    await waitFor(() =>
      expect(store.getState().convoyRoutes.routes[0].repeat).toBe(false)
    );
    const [url, init] = patchMock.mock.calls[0];
    expect(url).toMatch(/\/convoy-routes\/r-2$/);
    expect(init.method).toBe("PATCH");
    expect(JSON.parse(init.body)).toEqual({ repeat: false });
    expect(screen.getByText(/One-off: removed/)).toBeInTheDocument();
  });

  it("ticks the hidden overlay again when a drop zone is added", async () => {
    // Overlay unticked (remembered from an earlier session): the zone was
    // saved but drawn on a hidden layer, so nothing seemed to happen.
    mockFetch(201, { id: "dz-9", name: "DZ", position: { lat: 1, lng: 2 } });
    const { store } = renderWithProviders(<MapLayers />, {
      preloadedState: {
        map: {
          center: { lat: 0, lng: 0 },
          hoveredEmitterId: null,
          hoveredEmitterSource: null,
          highlightEmitters: true,
          activeBaseMap: null,
          overlayStates: { [DROP_ZONE_OVERLAY]: false },
        },
      },
    });

    rightClick(1, 2);
    fireEvent.click(screen.getByText(/Add Drop Zone/));
    expect(store.getState().map.overlayStates[DROP_ZONE_OVERLAY]).toBe(true);
    fireEvent.click(screen.getByText(/Save/));
    await waitFor(() =>
      expect(store.getState().dropZones.zones).toHaveLength(1)
    );
    expect(store.getState().map.overlayStates[DROP_ZONE_OVERLAY]).toBe(true);
  });

  it("cancels a route in progress with Escape", () => {
    renderWithProviders(<MapLayers />);
    rightClick(1, 2);
    fireEvent.click(screen.getByText(/Add Convoy Route/));
    act(() => {
      mapHandlers.keydown({ originalEvent: { key: "Escape" } });
    });
    expect(screen.queryByText(/right-click to set end point/)).toBeNull();
  });
});
