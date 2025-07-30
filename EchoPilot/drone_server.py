import asyncio
import httpx
import math
from mcp.server.fastmcp import FastMCP
from mavsdk import System
from mavsdk.action import ActionError, OrbitYawBehavior

# ==============================================================================
# == Global Objects and Helpers
# ==============================================================================
mcp = FastMCP("PX4DroneControlServer")
drone = System()
is_drone_connected = False


def get_distance_metres(lat1, lon1, lat2, lon2):
    R = 6371e3
    phi1 = math.radians(lat1); phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1); delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi / 2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


# ==============================================================================
# == MCP Server Tool Definitions (More Robust and Better Docstrings)
# ==============================================================================

@mcp.tool()
async def pre_flight_check() -> dict:
    """
    Performs critical pre-flight safety checks to ensure the drone is armable.
    This verifies GPS lock, home position, and sensor health.
    This should be the first step in almost every mission plan.

    Args: None
    Returns: dict: A JSON object with "status" and "message".
    """
    if not is_drone_connected: return {"status": "Error", "message": "Drone is not connected."}
    print("Performing pre-flight checks...")
    try:
        async for health in drone.telemetry.health():
            if health.is_global_position_ok and health.is_home_position_ok and health.is_armable:
                print("-- Drone is armable. All pre-flight checks passed.")
                return {"status": "Success", "message": "All pre-flight checks passed. Drone is armable."}
            if not health.is_armable:
                print("-- Pre-flight check failed: Drone is not in an armable state.")
                break 
        return {"status": "Error", "message": "Pre-flight checks failed. Drone is not armable. Check sensors/calibration."}
    except asyncio.TimeoutError: return {"status": "Error", "message": "Pre-flight check timed out."}

@mcp.tool()
async def arm_and_takeoff(altitude_meters: float) -> dict:
    """
    Arms the drone's motors and takes off vertically to a specific altitude.
    Waits until the drone reaches the target altitude before completing.

    Args:
        altitude_meters (float): The target altitude in meters relative to the ground.

    Returns: dict: A JSON object with "status" confirming successful takeoff.
    """
    
    if not is_drone_connected: return {"status": "Error", "message": "Drone is not connected."}
    try:
        print("-- Arming drone...")
        await drone.action.arm()
        await asyncio.sleep(1)
        print(f"-- Taking off to {altitude_meters} meters...")
        await drone.action.set_takeoff_altitude(altitude_meters)
        await drone.action.takeoff()
        print(f"-- Monitoring altitude... Target: {altitude_meters}m")
        async for position in drone.telemetry.position():
            if position.relative_altitude_m >= altitude_meters * 0.95:
                print(f"-- Target altitude of {altitude_meters}m reached!")
                break
        return {"status": "Success", "message": "Arm and takeoff successful."}
    except ActionError as e: return {"status": "Error", "message": f"Arm/Takeoff failed: {e}"}


@mcp.tool()
async def get_coordinates_for_location(location_name: str) -> dict:
    """
    Converts a human-readable location name (e.g., "Eiffel Tower") into GPS coordinates.

    Args:
        location_name (str): The name of the location (e.g., "Eiffel Tower, Paris").

    Returns: dict: A JSON object with "status", "latitude", "longitude", and "address".
    """
  
    url = f"https://nominatim.openstreetmap.org/search?q={location_name.replace(' ', '+')}&format=json&limit=1"
    headers = {'User-Agent': 'DroneControlMCP/1.0'}
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, timeout=10.0)
            response.raise_for_status()
            data = response.json()
            if data: return {"status": "Success", "latitude": float(data[0]["lat"]), "longitude": float(data[0]["lon"]), "address": data[0]["display_name"]}
            return {"status": "Error", "message": f"Could not find coordinates for '{location_name}'."}
    except Exception as e: return {"status": "Error", "message": f"Geocoding or network request failed: {e}"}


@mcp.tool()
async def fly_to_coordinates(latitude: float, longitude: float, altitude_meters: float | None = None, velocity_ms: float | None = None) -> dict:
    """
    Flies the drone to a specific GPS coordinate. Waits for arrival before completing.

    Args:
        latitude (float): The target latitude.
        longitude (float): The target longitude.
        altitude_meters (float, optional): The target absolute altitude (AMSL). If not provided, maintains current altitude.
        velocity_ms (float, optional): The speed for this flight leg in m/s. If not provided, a default speed of 5.0 m/s will be used.

    Returns: dict: A JSON object with "status" confirming successful arrival.
    """
    if not is_drone_connected: return {"status": "Error", "message": "Drone is not connected."}
    
    
    speed_to_use = velocity_ms if velocity_ms is not None else 5.0
    
    final_altitude = altitude_meters
    if final_altitude is None:
        try:
            position = await drone.telemetry.position().__anext__()
            final_altitude = position.absolute_altitude_m
        except StopAsyncIteration: return {"status": "Error", "message": "Failed to get current altitude."}
    
    print(f"-- Flying to {latitude}, {longitude} at {speed_to_use} m/s...")
    try:
        # Set speed for this specific flight leg
        await drone.action.set_current_speed(speed_to_use)
        await drone.action.goto_location(latitude, longitude, final_altitude, 0)
        
        arrival_threshold_meters = 5.0
        while True:
            await asyncio.sleep(2)
            try:
                # Heartbeat ping
                print("-- Sending heartbeat ping to drone...")
                await drone.action.set_current_speed(speed_to_use)
                
                current_pos = await drone.telemetry.position().__anext__()
                distance_to_target = get_distance_metres(current_pos.latitude_deg, current_pos.longitude_deg, latitude, longitude)
                print(f"-- Distance to target: {distance_to_target:.2f} meters...")
                
                if distance_to_target < arrival_threshold_meters:
                    print("-- Arrived at target location!")
                    break
            except StopAsyncIteration: 
                return {"status": "Error", "message": "Telemetry lost during flight."}

        print("-- Arrived. Stabilizing for 2 seconds...")
        await asyncio.sleep(2)
        return {"status": "Success", "message": "Navigation successful and arrival confirmed."}
    except ActionError as e:
        return {"status": "Error", "message": f"Goto location failed: {e}"}
    

@mcp.tool()
async def fly_relative(forward_meters: float = 0, right_meters: float = 0, down_meters: float = 0) -> dict:
    """
    Commands the drone to fly a certain distance relative to its current position and heading.

    Args:
        forward_meters (float, optional): Distance to fly forward in meters. Use a negative value to fly backward. Defaults to 0.
        right_meters (float, optional): Distance to fly to the right in meters. Use a negative value to fly left. Defaults to 0.
        down_meters (float, optional): Distance to fly down in meters. Use a negative value to fly up. Defaults to 0.

    Returns:
        dict: A JSON object confirming the relative move is complete.
    """
    if not is_drone_connected:
        return {"status": "Error", "message": "Drone is not connected."}

    print(f"-- Flying relative: {forward_meters}m forward, {right_meters}m right, {down_meters}m down...")
    
    try:
        # Get the current position and heading
        position = await drone.telemetry.position().__anext__()
        heading_deg = await drone.telemetry.heading().__anext__()

        # Simple trigonometry to calculate the new GPS coordinate
        earth_radius = 6378137.0
        # Calculate offset in radians
        lat_offset = (forward_meters * math.cos(math.radians(heading_deg.heading_deg)) - right_meters * math.sin(math.radians(heading_deg.heading_deg))) / earth_radius
        lon_offset = (forward_meters * math.sin(math.radians(heading_deg.heading_deg)) + right_meters * math.cos(math.radians(heading_deg.heading_deg))) / (earth_radius * math.cos(math.radians(position.latitude_deg)))

        # Convert radians to degrees and add to current position
        new_latitude = position.latitude_deg + math.degrees(lat_offset)
        new_longitude = position.longitude_deg + math.degrees(lon_offset)
        
        # Adjust altitude
        new_altitude = position.absolute_altitude_m - down_meters

        print(f"-- Calculated new target: Lat {new_latitude}, Lon {new_longitude}")

        # Reuse the robust goto_location logic to fly to the new point
        # You can call other async functions directly
        return await fly_to_coordinates(new_latitude, new_longitude, new_altitude)

    except (ActionError, StopAsyncIteration) as e:
        return {"status": "Error", "message": f"Failed to execute relative flight: {e}"}    

@mcp.tool()
async def do_orbit(latitude: float, longitude: float, radius_meters: float, velocity_ms: float | None = None) -> dict:
    """
    Flies a circle around a GPS point for a fixed duration of 30 seconds.

    Args:
        latitude (float): The latitude of the center point.
        longitude (float): The longitude of the center point.
        radius_meters (float): The radius of the circle in meters.
        velocity_ms (float, optional): The speed for the orbit in m/s. If not provided, a default of 5.0 m/s is used.

    Returns:
        dict: A JSON object confirming the orbit action was executed for 30 seconds.
    """
    if not is_drone_connected: return {"status": "Error", "message": "Drone is not connected."}
    
    speed_to_use = velocity_ms if velocity_ms is not None else 5.0

    print(f"-- Initiating orbit at {speed_to_use} m/s...")
    try:
        position = await drone.telemetry.position().__anext__()
        absolute_altitude_m = position.absolute_altitude_m
        
        # Start the orbit action
        await drone.action.do_orbit(
            radius_m=radius_meters, 
            velocity_ms=speed_to_use, 
            yaw_behavior=OrbitYawBehavior.HOLD_FRONT_TO_CIRCLE_CENTER, 
            latitude_deg=latitude, 
            longitude_deg=longitude, 
            absolute_altitude_m=absolute_altitude_m
        )
        
        
        orbit_duration = 60  # You can change this to any duration you want    
        print(f"-- Orbiting for a fixed duration of {orbit_duration} seconds.")
        await asyncio.sleep(orbit_duration)
        
        print("-- Orbit time complete. Holding position to stabilize...")
        await drone.action.hold()
        await asyncio.sleep(2)
        
        return {"status": "Success", "message": f"Orbit action completed after {orbit_duration} seconds."}
    except (ActionError, StopAsyncIteration) as e:
        return {"status": "Error", "message": f"Orbit failed: {e}"}

@mcp.tool()
async def land() -> dict:
    """
    Commands the drone to land at its current position.
    
    Args: None
    Returns: dict: A JSON object with "status" confirming a successful landing.
    """
    
    if not is_drone_connected: return {"status": "Error", "message": "Drone is not connected."}
    print("-- Landing command issued...")
    try:
        await drone.action.land()
        print("-- Monitoring for landing completion...")
        async for is_armed in drone.telemetry.armed():
            if not is_armed:
                print("-- Landing and disarm confirmed!")
                break
        return {"status": "Success", "message": "Landing successful."}
    except ActionError as e: return {"status": "Error", "message": f"Landing failed: {e}"}

@mcp.tool()
async def return_to_launch() -> dict:
    """
    Commands the drone to return to its original take-off location and land.

    Args: None
    Returns: dict: A JSON object confirming a successful return and landing.
    """
    
    if not is_drone_connected: return {"status": "Error", "message": "Drone is not connected."}
    print("-- Return to Launch (RTL) command issued...")
    try:
        await drone.action.return_to_launch()
        print("-- Monitoring for landing completion at launch point...")
        async for is_armed in drone.telemetry.armed():
            if not is_armed:
                print("-- RTL landing and disarm confirmed!")
                break
        return {"status": "Success", "message": "Return to launch successful."}
    except ActionError as e: return {"status": "Error", "message": f"RTL failed: {e}"}

async def main():
    
    global is_drone_connected
    print("Attempting to connect to drone...")
    await drone.connect(system_address="udp://:14540")
    async for state in drone.core.connection_state():
        if state.is_connected:
            print("-- Drone Connected!")
            is_drone_connected = True
            break
    if is_drone_connected:
        print("Starting MCP server. Awaiting commands from the model...")
        await mcp.run_stdio_async()
    else:
        print("Could not connect to the drone. MCP server will not start.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nServer terminated by user.")