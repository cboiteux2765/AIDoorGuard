import os
import sys
import asyncio
from typing import Optional

try:
    from bleak import BleakScanner, BleakClient
except Exception as e:
    print("[ble] ERROR: bleak is not installed. Run 'pip install bleak' in your Windows venv.")
    raise

async def pick_device(name_hint: Optional[str]) -> Optional[str]:
    print("[ble] Scanning for BLE devices (5s)...")
    devices = await BleakScanner.discover(timeout=5.0)
    if not devices:
        print("[ble] No BLE devices found.")
        return None

    print("\n[ble] Found devices:")
    for i, d in enumerate(devices):
        print(f"  [{i}] name={d.name!r} address={d.address}")

    if name_hint:
        for d in devices:
            if (d.name or "").strip() == name_hint.strip():
                print(f"[ble] Chose by name: {d.name!r} -> {d.address}")
                return d.address

    # Fallback: pick first
    choice = devices[0]
    print(f"[ble] Defaulting to first device: {choice.name!r} -> {choice.address}")
    return choice.address

async def inspect(address: str):
    print(f"[ble] Connecting to {address}...")
    async with BleakClient(address) as client:
        print("[ble] Connected. Enumerating services & characteristics...\n")
        services = await client.get_services()
        for svc in services:
            print(f"Service: {svc.uuid} ({svc.description})")
            for ch in svc.characteristics:
                props = ",".join(sorted(ch.properties))
                print(f"  Characteristic: {ch.uuid} props=[{props}]")
            print("")
    print("[ble] Done.")

async def main():
    # Usage: python ble_inspect.py [address]
    address = sys.argv[1] if len(sys.argv) > 1 else None
    name_hint = os.getenv("BLE_DEVICE_NAME", "") or None

    if not address:
        address = await pick_device(name_hint)
    if not address:
        return
    await inspect(address)

if __name__ == "__main__":
    asyncio.run(main())
