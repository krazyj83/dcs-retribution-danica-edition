import {
  CONVOY_SPEED_KPH,
  describeDrive,
  driveEstimate,
  formatMinutes,
  straightLineKm,
} from "./convoyTime";

describe("convoy drive time", () => {
  it("measures the straight-line distance", () => {
    // One degree of latitude is about 111 km.
    expect(straightLineKm({ lat: 42, lng: 42 }, { lat: 43, lng: 42 })).toBeCloseTo(
      111.2,
      0
    );
    expect(straightLineKm({ lat: 42, lng: 42 }, { lat: 42, lng: 42 })).toBe(0);
  });

  it("gives a road time range at convoy speed", () => {
    // 40 km straight: 48-60 km by road at 40 km/h = 72-90 min.
    const a = { lat: 42, lng: 42 };
    const b = { lat: 42 + 40 / 111.195, lng: 42 };
    const e = driveEstimate(a, b);
    expect(CONVOY_SPEED_KPH).toBe(40);
    expect(e.km).toBeCloseTo(40, 1);
    expect(e.minMinutes).toBe(72);
    expect(e.maxMinutes).toBe(90);
  });

  it("formats minutes and hours", () => {
    expect(formatMinutes(45)).toBe("45 min");
    expect(formatMinutes(60)).toBe("1 h");
    expect(formatMinutes(90)).toBe("1 h 30 min");
  });

  it("describes a route in one line", () => {
    const a = { lat: 42, lng: 42 };
    const b = { lat: 42 + 40 / 111.195, lng: 42 };
    expect(describeDrive(a, b)).toBe(
      "40 km · about 1 h 12 min – 1 h 30 min by road at 40 km/h"
    );
  });
});
