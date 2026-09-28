import { renderWithProviders } from "../../testutils";
import SupplyStatusLayer from "./SupplyStatusLayer";
import { screen, waitFor } from "@testing-library/react";
import { PropsWithChildren } from "react";
import { statusColor, supplyLines } from "./supplyText";
import type { BaseSupply } from "../../api/supplyStatusSlice";

const rings: any[] = [];

jest.mock("react-leaflet", () => ({
  LayerGroup: (props: PropsWithChildren<any>) => <div>{props.children}</div>,
  CircleMarker: (props: PropsWithChildren<any>) => {
    rings.push(props);
    return <div>{props.children}</div>;
  },
  Tooltip: (props: PropsWithChildren<any>) => <span>{props.children}</span>,
}));

const base = (over: Partial<BaseSupply>): BaseSupply => ({
  id: "b1",
  name: "Larnaca",
  position: { lat: 34.9, lng: 33.6 },
  fuel: 120,
  fuel_capacity: 1000,
  ammunition: 600,
  ammunition_capacity: 1000,
  supplies: 500,
  supplies_capacity: 1000,
  fuel_turns_left: 1.6,
  unlimited_fuel: false,
  status: "low",
  reasons: ["fuel for 1.6 turns", "fuel 12%"],
  ...over,
});

describe("SupplyStatusLayer", () => {
  afterEach(() => {
    jest.restoreAllMocks();
    rings.length = 0;
  });

  it("draws a ring per base coloured by status, with the numbers", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () =>
        Promise.resolve([
          base({}),
          base({ id: "b2", name: "Paphos", status: "ok", reasons: [], fuel_turns_left: null }),
        ]),
    }) as any;

    renderWithProviders(<SupplyStatusLayer />);

    await waitFor(() =>
      expect(screen.getByText(/Larnaca — supply Low/)).toBeInTheDocument()
    );
    expect(screen.getByText(/Paphos — supply OK/)).toBeInTheDocument();
    expect(screen.getByText(/~1.6 turns left/)).toBeInTheDocument();
    const last = rings.slice(-2);
    expect(last[0].pathOptions.color).toBe(statusColor("low"));
    expect(last[1].pathOptions.color).toBe(statusColor("ok"));
    expect((global.fetch as jest.Mock).mock.calls[0][0]).toMatch(
      /\/logistics\/supply-status$/
    );
  });

  it("describes unlimited fuel and critical bases", () => {
    const lines = supplyLines(
      base({ unlimited_fuel: true, status: "critical", reasons: ["out of ammunition"] })
    );
    expect(lines[0]).toMatch(/\(unlimited\)/);
    expect(lines[lines.length - 1]).toBe("⚠ out of ammunition");
    expect(statusColor("critical")).toBe("#e74c3c");
  });
});
