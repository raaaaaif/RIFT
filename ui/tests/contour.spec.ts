import { expect, test } from "@playwright/test";
import { cellOutline, isolines, smooth } from "../src/contour";

test.describe("marching squares", () => {
  test("a single raised centre gives one closed diamond half a cell from it", () => {
    const lines = isolines([[0, 0, 0], [0, 1, 0], [0, 0, 0]], 0.5);
    expect(lines).toHaveLength(1);
    const [line] = lines;
    expect(line[0]).toEqual(line[line.length - 1]);
    expect(line).toHaveLength(5);
    for (const [x, y] of line) expect(Math.abs(x - 1) + Math.abs(y - 1)).toBeCloseTo(0.5, 6);
  });

  test("a step between two rows gives one straight line at the interpolated height", () => {
    const col = [0, 10, 10];
    const lines = isolines([col, col, col, col], 2);
    expect(lines).toHaveLength(1);
    expect(lines[0]).toHaveLength(4);
    for (const [, y] of lines[0]) expect(y).toBeCloseTo(0.2, 6);
  });

  test("saddles follow the mean of the corners", () => {
    expect(isolines([[1, 0], [0, 1]], 0.5)).toHaveLength(2);
    expect(isolines([[1, 0], [0, 1]], 0.5).flat()).toHaveLength(4);
  });

  test("smoothing keeps open endpoints and closed loops closed", () => {
    const open = smooth([[0, 0], [1, 1], [2, 0]]);
    expect(open[0]).toEqual([0, 0]);
    expect(open[open.length - 1]).toEqual([2, 0]);
    const loop = smooth(isolines([[0, 0, 0], [0, 1, 0], [0, 0, 0]], 0.5)[0]);
    expect(loop[0]).toEqual(loop[loop.length - 1]);
  });

  test("cell outlines trace only borders between inside and outside cells", () => {
    expect(cellOutline([[true, false], [false, false]])).toHaveLength(2);
    expect(cellOutline([[true, true], [true, true]])).toHaveLength(0);
    expect(cellOutline([[false, false, false], [false, true, false], [false, false, false]])).toHaveLength(4);
  });

  test("non-finite samples are skipped, not drawn", () => {
    expect(isolines([[Number.NaN, 0], [1, 1]], 0.5)).toHaveLength(0);
  });
});
