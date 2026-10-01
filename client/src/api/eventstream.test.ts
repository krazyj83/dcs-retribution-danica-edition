import { handleStreamedEvents } from "./eventstream";

// A stream message with nothing in it, so a test only sets what it checks.
const empty = (): any => ({
  frozen_combats: [],
  updated_flight_positions: {},
  new_combats: [],
  updated_combats: [],
  ended_combats: [],
  navmesh_updates: {},
  updated_unculled_zones: [],
  threat_zones_updated: {},
  new_flights: [],
  updated_flights: [],
  deleted_flights: [],
  selected_flight: null,
  deselected_flight: false,
  updated_front_lines: [],
  deleted_front_lines: [],
  updated_tgos: [],
  updated_control_points: [],
  updated_iads: [],
  deleted_iads: [],
  updated_supply_routes: [],
  reset_on_map_center: null,
  game_unloaded: false,
  new_turn: false,
});

describe("handleStreamedEvents", () => {
  it("reloads the supply rings when base stock changed", () => {
    const dispatch = jest.fn(() => Promise.resolve());
    handleStreamedEvents(dispatch as any, { ...empty(), supply_status_changed: true });
    expect(dispatch).toHaveBeenCalledTimes(1);
    expect(typeof (dispatch.mock.calls[0] as any[])[0]).toBe("function"); // the fetch thunk
  });

  it("does nothing for an empty message", () => {
    const dispatch = jest.fn();
    handleStreamedEvents(dispatch as any, empty());
    expect(dispatch).not.toHaveBeenCalled();
  });
});
