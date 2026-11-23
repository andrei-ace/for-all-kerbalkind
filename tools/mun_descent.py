"""Finite-thrust descent check for Jamestown on the stock Mun, in metres, seconds and tonnes."""

from math import hypot, log, sqrt


def polar_descent(orbit_radius, body_radius, terrain_height, wet, dry, thrust, exhaust_velocity, step=0.05):
    # KSP 1.12.5 CelestialBody.gravParameter, measured in the campaign.
    mu = 65_138_397_520.780693
    radius = orbit_radius
    floor = body_radius + terrain_height
    mass = wet
    tangential = sqrt(mu / radius)
    radial = 0.0
    # A short retrograde burn lowers the predicted periapsis. The main braking
    # burn starts above the shelf, before the vehicle reaches that periapsis.
    periapsis = body_radius + 2_000
    deorbit_speed = sqrt(mu * (2 / radius - 2 / (radius + periapsis)))
    deorbiting = True
    for _ in range(int(3600 / step)):
        height = radius - floor
        if height <= 0:
            if hypot(tangential, radial) > 2:
                raise ValueError("Jamestown crossed the landing shelf above 2 m/s")
            return exhaust_velocity * log(wet / mass), exhaust_velocity * log(mass / dry)
        if mass <= dry:
            raise ValueError("Jamestown exhausted its descent propellant")

        acceleration = thrust / mass
        gravity = mu / radius**2
        curvature = tangential**2 / radius
        outward = along_track = 0.0
        if deorbiting and tangential > deorbit_speed:
            along_track = -acceleration
        else:
            deorbiting = False
            if height <= 6_000:
                # Limit descent to 37 m/s while removing horizontal speed, then
                # slow vertically at 0.8 m/s² toward a 1 m/s touchdown.
                rate = min(37, sqrt(1 + 2 * 0.8 * height))
                correction = (-rate - radial) / 2 + (0.8 if rate < 37 else 0)
                outward = max(0, min(acceleration, gravity - curvature + correction))
                lateral_limit = sqrt(max(0, acceleration**2 - outward**2))
                along_track = -min(lateral_limit, tangential / 2)

        radial_acceleration = curvature - gravity + outward
        tangential_acceleration = along_track - radial * tangential / radius
        radius += radial * step + 0.5 * radial_acceleration * step**2
        radial += radial_acceleration * step
        tangential += tangential_acceleration * step
        mass -= mass * hypot(outward, along_track) / exhaust_velocity * step
    raise ValueError("Jamestown did not reach the landing shelf")
