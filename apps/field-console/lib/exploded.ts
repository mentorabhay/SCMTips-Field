/**
 * Exploded-view geometry shared by the console model viewer (T4.057 / FR4.056 / PR4.09).
 *
 * p(t) = p0 + clamp(t, 0, 1) * v : at t = 0 a part sits at its assembled position, at t = 1 its
 * offset equals its explode vector, and in between it moves linearly.
 */
export type Vec3 = readonly [number, number, number];

export function clampT(t: number): number {
  if (Number.isNaN(t)) return 0;
  return Math.min(1, Math.max(0, t));
}

export function explodedPosition(p0: Vec3, v: Vec3, t: number): [number, number, number] {
  const c = clampT(t);
  return [p0[0] + c * v[0], p0[1] + c * v[1], p0[2] + c * v[2]];
}
